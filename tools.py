"""Hermes tool handlers: EquityLayer MCP calls plus local Follow Card state."""

from __future__ import annotations

import functools
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Callable

from . import formatters
from .harness_store import TAIPEI, HarnessStore, default_harness_store
from .profile_store import SECTORS, ProfileStore, default_profile_store, describe, validate_fields
from .watch_store import WatchStore, default_watch_store
from .watch_tools import WatchTools
from .track_tools import TrackTools
from . import dashboard as dashboard_page
from .harness_tools import HarnessTools
from .follows import FollowStore, apply_caller_action, build_record, default_store, is_due, target_of
from .mcp_client import DEFAULT_MCP_URL, McpClient, McpError

PACK_INDEX = "packs.json"
PACK_SHORT = {"optical_cpo": "CPO", "custom_asic": "ASIC", "space_infrastructure": "Space", "physical_ai": "Physical AI"}
PACK_INDEX_MAX_AGE = 12 * 3600

logger = logging.getLogger(__name__)

PRICING_URL = "https://equitylayer.io/pricing"
# Substrings of upstream error codes that mean authentication, entitlement or payment.
GATED_MARKERS = ("authentication", "authorization", "unauthorized", "entitle", "payment", "x402", "grant", "activation")
HINTS = {
    "unknown_research_pack": "Run el_research_pack with action list for valid ids.",
    "research_pack_unavailable": (
        "This pack is not available on this route. It may be retired or gated. Pick a public entry "
        "from el_research_pack (action list)."
    ),
    "upstream_unavailable": "EquityLayer could not be reached. Local follows are unchanged. Try again later.",
    "invalid_mcp_url": "Set mcp_url to https://equitylayer.io/mcp in this plugin's settings.",
    "invalid_arguments": "Fix the arguments named in the message and try again.",
}


def is_gated(code: str) -> bool:
    lowered = code.lower()
    return any(marker in lowered for marker in GATED_MARKERS)


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return default


def _text_arg(args: dict, name: str) -> str:
    value = args.get(name)
    return value.strip() if isinstance(value, str) else ""


def _missing(*names: str) -> dict:
    return {
        "ok": False,
        "error": "missing_argument",
        "argument": " or ".join(names),
        "message": f"Provide {' or '.join(names)}.",
    }


def _safe(method: Callable[..., dict]) -> Callable[..., str]:
    """Hermes handlers return a JSON string and must never raise."""

    @functools.wraps(method)
    def handler(self: "EquityLayerTools", args: dict | None = None, **kwargs: Any) -> str:
        return json.dumps(self.run(method, args), ensure_ascii=False)

    return handler


class EquityLayerTools(TrackTools, HarnessTools, WatchTools):
    def __init__(
        self,
        get_config: Callable[..., Any] | None = None,
        in_cron: Callable[[], bool] | None = None,
        store_factory: Callable[[], FollowStore] = default_store,
        transport: Any = None,
        harness_store_factory: Callable[[], HarnessStore] = default_harness_store,
        profile_store_factory: Callable[[], ProfileStore] = default_profile_store,
        watch_store_factory: Callable[[], WatchStore] = default_watch_store,
    ):
        self._get_config = get_config or (lambda key, default=None: default)
        self._in_cron = in_cron or (lambda: False)
        self._store_factory = store_factory
        self._transport = transport
        self._harness_store_factory = harness_store_factory
        self._profile_store_factory = profile_store_factory
        self._watch_store_factory = watch_store_factory
        self._plan_ids = None
        self._locked_ids: set[str] = set()

    # -- shared plumbing ---------------------------------------------------------------------------

    def run(self, method: Callable[..., dict], args: dict | None) -> dict:
        """Run a tool body and turn every failure into a structured error."""
        safe_args = args if isinstance(args, dict) else {}
        try:
            return method(self, safe_args)
        except McpError as exc:
            return self._error(exc, safe_args)
        except ValueError as exc:
            # Raised for an id that cannot be a local file name.
            return {"ok": False, "error": "invalid_argument", "message": str(exc)}
        except OSError as exc:
            logger.warning("EquityLayer local storage error: %s", exc)
            return {"ok": False, "error": "local_storage_error", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - a tool must report, not crash the agent turn
            logger.exception("EquityLayer tool failed")
            return {"ok": False, "error": "internal_error", "message": f"{type(exc).__name__}: {exc}"}

    def _error(self, exc: McpError, args: dict) -> dict:
        target = {k: args[k] for k in ("pack_id", "thesis_id", "id") if isinstance(args.get(k), str)}
        if is_gated(exc.code):
            return self._gated(exc.code, target)
        result = {"ok": False, "error": exc.code, "message": exc.message, **target}
        if exc.details:
            result["details"] = exc.details
        if exc.code in HINTS:
            result["hint"] = HINTS[exc.code]
        return result

    def _gated(self, upstream: str, target: dict) -> dict:
        return {
            "ok": False,
            "error": "entitlement_or_payment_required",
            "upstream_error": upstream,
            "hint": "This plugin holds no credential and never pays. Use public research or your own thesis harness.",
            "pricing_url": PRICING_URL,
            **target,
        }

    def _call(self, tool: str, arguments: dict) -> dict:
        url = str(self._get_config("mcp_url", default=DEFAULT_MCP_URL) or DEFAULT_MCP_URL)
        return McpClient(url, transport=self._transport).call_tool(tool, arguments)

    def _call_full(self, tool: str, arguments: dict) -> dict:
        """Events and due dates live on the same server's full tool list (/mcp/full), not a second service."""
        url = str(self._get_config("mcp_url", default=DEFAULT_MCP_URL) or DEFAULT_MCP_URL).rstrip("/")
        if not url.endswith("/mcp/full"):
            url = url + "/full"
        return McpClient(url, transport=self._transport).call_tool(tool, arguments)

    # -- dashboard ---------------------------------------------------------------------------------

    def _dashboard_root(self):
        return self._harness_store_factory().dir.parent

    def _render_dashboard(self, preview: dict | None = None, refresh_packs: bool = False):
        theses, _ = self._harness_store_factory().all()
        watchlists, _ = self._watch_store_factory().all()
        follows, _ = self._store_factory().all()
        followed = {f.get("target_id"): f for f in follows if f.get("target_kind") == "pack" and f.get("target_id")}
        target = self._dashboard_root() / dashboard_page.FILE_NAME
        packs, fetched_at = self._pack_index(refresh_packs)
        as_of = (datetime.fromtimestamp(fetched_at, TAIPEI).strftime("%Y-%m-%d %H:%M Taipei")
                 if fetched_at else None)
        page = dashboard_page.render(self._profile_store_factory().get(), theses, watchlists, preview=preview,
                                     saved_at=str(target), packs=packs, followed=followed, packs_as_of=as_of)
        return dashboard_page.write(self._dashboard_root(), page)

    # The last registry this plugin saw, so the dashboard can say which Research Packs are published.
    def _save_pack_index(self, entries: Any) -> list[dict]:
        rows = [{"id": e.get("id"), "kind": e.get("kind"), "title": e.get("title"), "theme_id": e.get("theme_id"),
                 "status": e.get("status"), "access": e.get("access"), "view": e.get("view"),
                 "url": (e.get("cite_as") or {}).get("url") if isinstance(e.get("cite_as"), dict) else None}
                for e in entries or [] if isinstance(e, dict) and e.get("id")]
        path = self._dashboard_root() / PACK_INDEX
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"fetched_at": time.time(), "entries": rows}, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
        return rows

    def _pack_index(self, refresh: bool = False) -> tuple[list[dict] | None, float | None]:
        """The cached registry and when it was fetched. Only an explicit dashboard render refreshes it (12 h);
        renders after a check use the cache, and the card says how old it is."""
        try:
            data = json.loads((self._dashboard_root() / PACK_INDEX).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        rows = data.get("entries") if isinstance(data, dict) and isinstance(data.get("entries"), list) else None
        try:
            fetched_at = float(data.get("fetched_at")) if rows is not None else None
        except (TypeError, ValueError):
            rows, fetched_at = None, None
        if refresh and (fetched_at is None or time.time() - fetched_at > PACK_INDEX_MAX_AGE):
            try:
                url = str(self._get_config("mcp_url", default=DEFAULT_MCP_URL) or DEFAULT_MCP_URL)
                payload = McpClient(url, transport=self._transport, timeout=8.0).call_tool("list_registry", {})
                rows, fetched_at = self._save_pack_index(payload.get("entries")), time.time()
            except Exception:  # noqa: BLE001 - the dashboard renders from the last registry it saw
                logger.info("EquityLayer registry not refreshed for the dashboard", exc_info=True)
        return rows, fetched_at

    def _preview(self, args: dict) -> dict | None:
        """Live readings shown before anything is saved, so the dashboard has something on the first turn."""
        if not args.get("preview_variables"):
            return None
        from .harness_store import today_taipei
        from .watch_tools import _row, _unavailable_row
        from .watch_store import validate_variables

        rows = []
        for variable in validate_variables(args.get("preview_variables")):
            try:
                row = _row(variable, self._call("get_variable", {"variable": variable}), None)
            except McpError as exc:
                row = _unavailable_row(variable, exc)
            row["new"] = False
            rows.append(row)
        title = " ".join(str(args.get("preview_title") or "Live readings").split())[:80]
        theme = args.get("preview_theme") if args.get("preview_theme") in dashboard_page.THEME_LABELS else None
        return {"title": title, "as_of": today_taipei(), "rows": rows, "theme": theme}

    def _refresh_dashboard(self) -> None:
        """Keep the local page current after a check. A failure here never fails the check."""
        try:
            self._render_dashboard()
        except Exception:  # noqa: BLE001
            logger.warning("EquityLayer dashboard not refreshed", exc_info=True)

    def _dashboard(self, args: dict) -> dict:
        path = self._render_dashboard(self._preview(args), refresh_packs=True)
        return {
            "ok": True,
            "artifact_file": str(path),
            # Hermes Desktop renders a ::preview directive live inside the message, so the dashboard is
            # in the chat itself rather than only under Artifacts.
            "markdown": (f"Your dashboard: what you follow, what needs you, recent events and what is due next, "
                         f"built on this machine.\n\n::preview{{file=\"{path}\" height=\"560\"}}\n\n"
                         f"It is saved at `{path}`. Reopen it any time with `/el dashboard` or from Artifacts."),
        }

    def _refuse_locked(self, entry_id: str, target: dict) -> dict | None:
        """Skip the network for an entry the registry already showed as non-public."""
        if entry_id in self._locked_ids:
            return self._gated("registry_access_not_public", target)
        return None

    # -- registry and research ---------------------------------------------------------------------

    def _registry(self, args: dict) -> dict:
        arguments = {"publisher": args["publisher"]} if _text_arg(args, "publisher") else {}
        payload = self._call("list_registry", arguments)
        entries = [self._compact_entry(e) for e in payload.get("entries") or [] if isinstance(e, dict)]
        if not arguments:
            try:
                self._save_pack_index(payload.get("entries"))
            except OSError:
                logger.info("EquityLayer registry not saved locally", exc_info=True)
        self._locked_ids = {e["id"] for e in entries if e["locked"]}
        return {
            "ok": True,
            "count": len(entries),
            "registry_url": payload.get("registry_url"),
            "availability_note": payload.get("availability_note"),
            "current_product_industries": payload.get("current_product_industries"),
            "entries": entries,
            "markdown": formatters.format_registry(
                entries,
                payload.get("registry_url"),
                note=payload.get("availability_note"),
                industries=payload.get("current_product_industries"),
            ),
        }

    def _compact_entry(self, entry: dict) -> dict:
        freshness = entry.get("freshness") if isinstance(entry.get("freshness"), dict) else {}
        access = entry.get("access")
        cite = entry.get("cite_as") if isinstance(entry.get("cite_as"), dict) else {}
        return {
            "id": entry.get("id"),
            "kind": entry.get("kind"),
            "title": entry.get("title"),
            "publisher": (entry.get("publisher") or {}).get("name") if isinstance(entry.get("publisher"), dict) else None,
            "status": entry.get("status"),
            "access": access,
            "locked": access != "public",
            "edition": entry.get("edition"),
            "coverage": entry.get("coverage"),
            "freshness": freshness.get("freshness"),
            "fresh_until": freshness.get("fresh_until"),
            "next_check_at": freshness.get("next_check_at"),
            "read": entry.get("read"),
            "follow": entry.get("follow"),
            "cite_as": cite.get("text"),
        }

    def _pack(self, args: dict) -> dict:
        pack_id = _text_arg(args, "pack_id")
        if not pack_id:
            return _missing("pack_id")
        refused = self._refuse_locked(pack_id, {"pack_id": pack_id})
        if refused:
            return refused
        arguments: dict = {"pack_id": pack_id}
        if _text_arg(args, "version"):
            arguments["version"] = args["version"]
        if args.get("symbols"):
            arguments["symbols"] = args["symbols"]
        pack = self._call("get_research_pack", arguments)
        if args.get("format") == "json":
            return {"ok": True, "pack_id": pack_id, "pack": pack}
        max_records = args.get("max_records")
        max_records = max_records if isinstance(max_records, int) and 1 <= max_records <= 50 else 10
        return {
            "ok": True,
            "pack_id": pack_id,
            "version": pack.get("pack_version"),
            "as_of": pack.get("as_of"),
            "fresh_until": pack.get("fresh_until"),
            "snapshot_hash": pack.get("snapshot_hash"),
            "source_attribution": (pack.get("source") or {}).get("attribution") if isinstance(pack.get("source"), dict) else None,
            "markdown": formatters.format_pack(pack, max_records),
        }

    def _scorecard(self, args: dict) -> dict:
        entry_id = _text_arg(args, "id")
        if not entry_id:
            return _missing("id")
        refused = self._refuse_locked(entry_id, {"id": entry_id})
        if refused:
            return refused
        data = self._call("get_pack_scorecard", {"id": entry_id})
        if args.get("format") == "json":
            return {"ok": True, "id": entry_id, "scorecard": data}
        return {
            "ok": True,
            "id": entry_id,
            "scorecard": data.get("scorecard"),
            "cite_as": (data.get("cite_as") or {}).get("text") if isinstance(data.get("cite_as"), dict) else None,
            "markdown": formatters.format_scorecard(data),
        }

    # -- follows -----------------------------------------------------------------------------------

    def _schedule_hint(self, record: dict | None = None) -> str:
        when = f" after {record['next_check_at']}" if record and record.get("next_check_at") else ""
        follow_id = record.get("follow_id") if record else "<follow_id>"
        return (
            f"Run `/el check {follow_id}`{when}, or let the daily check (`/blueprint equitylayer:daily-check`) "
            "cover it."
        )

    def _follow_create(self, args: dict) -> dict:
        thesis_id, pack_id = _text_arg(args, "thesis_id"), _text_arg(args, "pack_id")
        if bool(thesis_id) == bool(pack_id):
            return {
                "ok": False,
                "error": "invalid_argument",
                "message": "Provide exactly one of thesis_id or pack_id.",
            }
        kind, target = ("view", thesis_id) if thesis_id else ("pack", pack_id)
        arguments = {"thesis_id": thesis_id} if thesis_id else {"pack_id": pack_id}
        refused = self._refuse_locked(target, arguments)
        if refused:
            return refused
        store = self._store_factory()
        # Keep the original baseline: a fresh card would silently hide changes since it was created.
        existing = store.find_target(kind, target)
        if existing:
            summary = existing.get("pack") if isinstance(existing.get("pack"), dict) else None
            if kind == "pack" and (not summary or (summary.get("variables") and not existing.get("readings_id"))):
                # A follow made before its Pack could be read, or by an older version: complete it now.
                self._attach_pack(store, existing)
                self._refresh_dashboard()
            return self._follow_result(existing, already_following=True)
        record = self._create_record(arguments)
        path = store.save(record)
        if kind == "pack":
            self._attach_pack(store, record)
            self._refresh_dashboard()
        return self._follow_result(record, path=str(path))

    def _attach_pack(self, store: FollowStore, record: dict) -> None:
        """Keep the Pack's thesis on the follow, and follow the readings it watches as its evidence.

        Best effort: if the Pack can't be read now, the follow still works and shows its id."""
        try:
            summary = formatters.pack_summary(self._call("get_research_pack", {"pack_id": record.get("target_id")}))
        except Exception as exc:  # noqa: BLE001 - the follow itself is saved; the summary is extra
            logger.info("EquityLayer Pack not read after following: %s", getattr(exc, "code", type(exc).__name__))
            return
        if not summary:
            return
        record["pack"] = summary
        variables = summary.get("variables") or []
        if variables and not record.get("readings_id"):
            theme = summary.get("theme_id") if summary.get("theme_id") in dashboard_page.THEME_LABELS else None
            name = " ".join(str(summary.get("title") or "").split())
            name = name if len(name) <= 62 else name[:61].rsplit(" ", 1)[0] + "…"
            title = f"{PACK_SHORT.get(theme, 'Research')} Pack readings: {name}" if name else \
                f"{PACK_SHORT.get(theme, 'Research')} Pack: the readings it watches"
            watch_id = self._unique_item_id(title)
            try:
                saved = self._watch_save({"_new_id": watch_id, "title": title, "variables": variables,
                                          "theme": theme})
                if saved.get("ok"):
                    self._watch_store().link_follow(watch_id, record.get("follow_id"))
                    record["readings_id"] = watch_id
            except Exception as exc:  # noqa: BLE001 - the follow works without its readings
                logger.info("EquityLayer Pack readings not saved: %s", type(exc).__name__)
        store.save(record)

    def _create_record(self, arguments: dict) -> dict:
        data = self._call("create_research_follow", arguments)
        card = data.get("follow_card")
        if not isinstance(card, dict):
            raise McpError("invalid_mcp_response", "The server did not return a Follow Card.")
        return build_record(card, data.get("caller_action"))

    def _follow_result(self, record: dict, *, already_following: bool = False, path: str | None = None) -> dict:
        hint = self._schedule_hint(record)
        result = {
            "ok": True,
            "already_following": already_following,
            "follow_id": record.get("follow_id"),
            "target_kind": record.get("target_kind"),
            "target_id": record.get("target_id"),
            "next_check_at": record.get("next_check_at"),
            "fresh_until": record.get("fresh_until"),
            "schedule_hint": hint,
            "markdown": formatters.format_follow_created(record, hint, already_following),
        }
        if path:
            result["stored_at"] = path
        return result

    def _follow_check(self, args: dict) -> dict:
        follow_id = _text_arg(args, "follow_id")
        card = args.get("follow_card")
        if args.get("accept_next"):
            return self._accept_next(follow_id)
        if isinstance(card, dict):
            # A supplied card stays with the caller: nothing is written locally.
            result = self._check_card(card)
            return self._check_response([result], [], due_mode=False)
        store = self._store_factory()
        if follow_id:
            record = store.get(follow_id)
            if record is None:
                return self._unknown_follow(follow_id)
            return self._check_response([self._check_record(store, record)], [], due_mode=False)
        records, _ = store.all()
        # A card awaiting review is not re-sent, so a daily job does not repeat the same alert.
        awaiting = [r for r in records if r.get("pending_review")]
        due = [r for r in records if not r.get("pending_review") and is_due(r.get("next_check_at"))]
        results = [self._check_record(store, r) for r in due]
        return self._check_response(results, awaiting, due_mode=True)

    def _unknown_follow(self, follow_id: str) -> dict:
        return {
            "ok": False,
            "error": "unknown_follow",
            "follow_id": follow_id,
            "hint": "Run el_list (/el list) for the ids you track.",
        }

    def _check_card(self, card: dict) -> dict:
        target = target_of(card)
        base = {"follow_id": card.get("follow_id"), "target_id": target[1] if target else None}
        try:
            data = self._call("check_research_follow", {"follow_card": card})
        except McpError as exc:
            gated = is_gated(exc.code)
            return {
                **base,
                "status": "error",
                "error": "entitlement_or_payment_required" if gated else exc.code,
                "message": PRICING_URL if gated else exc.message,
                "needs_review": False,
            }
        action = data.get("caller_action") if isinstance(data.get("caller_action"), dict) else {}
        status = str(data.get("status") or "unknown")
        next_card = data.get("next_card") if isinstance(data.get("next_card"), dict) else None
        return {
            **base,
            "status": status,
            "needs_review": "review" in status or next_card is not None,
            "message": action.get("message"),
            "next_check_at": action.get("next_check_at"),
            "variable_changes": data.get("variable_changes"),
            "new_events": data.get("new_events"),
            "new_version": action.get("new_version"),
            "read": action.get("read"),
            "next_card": next_card,
            "_card": data.get("follow_card"),
            "_action": action,
        }

    def _check_record(self, store: FollowStore, record: dict) -> dict:
        result = self._check_card(record["follow_card"])
        if isinstance(record.get("pack"), dict):
            result["title"] = record["pack"].get("title")
            result["linked"] = bool(record.get("readings_id"))
        current = (record.get("pack") or {}).get("revision") or (record.get("follow_card") or {}).get("version")
        upcoming = result.get("new_version") or (result.get("next_card") or {}).get("version")
        # New data for a watched reading keeps the revision; a new revision is EquityLayer changing the Pack.
        result["revision_changed"] = bool(upcoming) and str(upcoming) != str(current)
        if result["status"] == "error":
            return result
        apply_caller_action(record, result.get("_action"))
        if result["needs_review"]:
            # The stored card stays as it is until the user accepts.
            record["pending_review"] = {
                k: result.get(k)
                for k in ("status", "message", "new_version", "read", "next_card", "variable_changes", "new_events",
                          "revision_changed")
            }
        else:
            if isinstance(result.get("_card"), dict):
                record["follow_card"] = result["_card"]
            record["pending_review"] = None
        store.save(record)
        return result

    def _check_response(self, results: list[dict], awaiting: list[dict], due_mode: bool) -> dict:
        public = [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]
        return {
            "ok": True,
            "mode": "due" if due_mode else "single",
            "checked": public,
            "errors": sum(1 for r in public if r.get("status") == "error"),
            "needs_review": sum(1 for r in public if r.get("needs_review")),
            "awaiting_review": [
                {"follow_id": r.get("follow_id"), "target_id": r.get("target_id")} for r in awaiting
            ],
            "markdown": formatters.format_check_run(public, awaiting, due_mode),
        }

    def _accept_next(self, follow_id: str) -> dict:
        if self._in_cron():
            return {
                "ok": False,
                "error": "accept_requires_user",
                "message": "A person must review an update. Scheduled runs never accept it.",
            }
        if not follow_id:
            return _missing("follow_id")
        store = self._store_factory()
        record = store.get(follow_id)
        if record is None:
            return self._unknown_follow(follow_id)
        pending = record.get("pending_review")
        if not pending:
            return {
                "ok": False,
                "error": "nothing_to_accept",
                "follow_id": follow_id,
                "message": "This follow has no update awaiting review.",
            }
        if isinstance(pending.get("next_card"), dict):
            new_record = build_record(pending["next_card"])
        else:
            # Pack cards name create_research_follow as the way to move to the new version.
            key = "thesis_id" if record.get("target_kind") == "view" else "pack_id"
            new_record = self._create_record({key: record.get("target_id")})
        for key in ("pack", "readings_id"):
            if record.get(key) and not new_record.get(key):
                new_record[key] = record[key]
        store.save(new_record)
        if new_record.get("follow_id") != follow_id:
            store.delete(follow_id)
            if new_record.get("readings_id"):
                try:
                    self._watch_store().link_follow(new_record["readings_id"], new_record.get("follow_id"))
                except Exception:  # noqa: BLE001 - a missing or unreadable watchlist leaves the Pack on its own
                    new_record["readings_id"] = None
                    store.save(new_record)
        if new_record.get("target_kind") == "pack":
            try:  # the new version may change the hypotheses
                summary = formatters.pack_summary(self._call("get_research_pack", {"pack_id": new_record.get("target_id")}))
                if summary:
                    new_record["pack"] = summary
                    store.save(new_record)
                    watch = self._watch_store().get(new_record["readings_id"]) if new_record.get("readings_id") else None
                    if watch and summary.get("variables") and summary["variables"] != watch.get("variables"):
                        self._watch_save({"watch_id": watch["id"], "title": watch.get("title"),
                                          "variables": summary["variables"], "theme": watch.get("theme")})
            except Exception:  # noqa: BLE001 - the accepted card is saved either way
                logger.info("EquityLayer Pack not re-read after accepting an update")
        return {
            **self._follow_result(new_record),
            "accepted": True,
            "previous_follow_id": follow_id,
            "markdown": (
                f"**Accepted.** `{new_record.get('target_id')}` now follows from the new baseline as "
                f"`{new_record.get('follow_id')}`. Next check: {new_record.get('next_check_at') or 'unknown'}."
            ),
        }

    def _follow_list(self, args: dict) -> dict:
        records, unreadable = self._store_factory().all()
        rows = []
        for record in records:
            review = bool(record.get("pending_review"))
            due = is_due(record.get("next_check_at"))
            if args.get("due_only") and not (due or review):
                continue
            rows.append(
                {
                    "follow_id": record.get("follow_id"),
                    "target_kind": record.get("target_kind"),
                    "target_id": record.get("target_id"),
                    "fresh_until": record.get("fresh_until"),
                    "next_check_at": record.get("next_check_at"),
                    "state": "needs review" if review else "due" if due else "waiting",
                }
            )
        hint = self._schedule_hint()
        return {
            "ok": True,
            "count": len(rows),
            "follows": rows,
            "unreadable": unreadable,
            "schedule_hint": hint,
            "markdown": formatters.format_follow_list(rows, unreadable, hint),
        }

    def _follow_remove(self, args: dict) -> dict:
        """Stop following locally. Slash command only: the model has no delete tool."""
        follow_id = _text_arg(args, "follow_id")
        if not follow_id:
            return _missing("follow_id")
        if not self._store_factory().delete(follow_id):
            return self._unknown_follow(follow_id)
        return {"ok": True, "follow_id": follow_id, "markdown": f"Removed local follow `{follow_id}`."}

    # -- Hermes tool handlers ----------------------------------------------------------------------

    # -- research profile (local) -----------------------------------------------------------------

    def _profile_get(self, args: dict) -> dict:
        profile = self._profile_store_factory().get()
        harnesses, _ = self._harness_store_factory().all()
        watchlists, _ = self._watch_store_factory().all()
        follows, _ = self._store_factory().all()
        about = describe(profile)
        lines = ["**Your EquityLayer research profile** (this machine only)", ""]
        lines.append(f"- {about[0].upper() + about[1:]}." if about else "- Not set up yet. Type `/equitylayer:start`.")
        lines.append(f"- Tracked: {len(watchlists)} readings, {len(harnesses)} of your theses, "
                     f"{len(follows)} followed Research Pack(s) (`/el list`)")
        return {
            "ok": True,
            "markdown": "\n".join(lines),
            "profile": profile,
            "returning": bool(profile or harnesses or watchlists or follows),
            "saved_harnesses": [{"id": r.get("id"), "title": r.get("title")} for r in harnesses][:15],
            "saved_watchlists": [{"id": r.get("id"), "title": r.get("title"), "variables": r.get("variables")}
                                 for r in watchlists][:10],
            "sectors": [dict(s) for s in SECTORS],
            "stored": "local only; never sent to EquityLayer",
        }

    def _profile_save(self, args: dict) -> dict:
        if self._in_cron():
            return {"ok": False, "error": "not_in_scheduled_run",
                    "message": "A scheduled run never changes the research profile."}
        fields = {k: v for k, v in args.items() if v is not None}
        if not fields:
            return {"ok": False, "error": "missing_argument", "argument": "a profile field",
                    "message": "Provide at least one of: sectors, has_view, check, check_time, timezone, language."}
        validate_fields(fields)  # raises ValueError → invalid_argument
        profile = self._profile_store_factory().save(fields)
        return {"ok": True, "profile": profile, "stored": "local only; never sent to EquityLayer"}

    el_list_registry = _safe(_registry)
    # The nine tools the model sees (one tracked object, three levels).
    el_profile = _safe(TrackTools._profile)
    el_plan = _safe(HarnessTools._plan)
    el_track = _safe(TrackTools._track)
    el_check = _safe(TrackTools._check)
    el_seen = _safe(TrackTools._seen)
    el_list = _safe(TrackTools._list)
    el_research_pack = _safe(TrackTools._research_pack)
    # Earlier per-kind tools: kept for the slash command and tests, not registered with Hermes.
    el_profile_get = _safe(_profile_get)
    el_watch_save = _safe(WatchTools._watch_save)
    el_watch_check = _safe(WatchTools._watch_check)
    el_watch_seen = _safe(WatchTools._watch_seen)
    el_watch_list = _safe(WatchTools._watch_list)
    el_dashboard_render = _safe(_dashboard)
    el_profile_save = _safe(_profile_save)
    el_get_pack = _safe(_pack)
    el_scorecard = _safe(_scorecard)
    el_follow_create = _safe(_follow_create)
    el_follow_check = _safe(_follow_check)
    el_follow_list = _safe(_follow_list)

    el_plan_thesis = _safe(HarnessTools._plan)
    el_get_variable = _safe(HarnessTools._variable)
    el_harness_save = _safe(HarnessTools._harness_save)
    el_harness_check = _safe(HarnessTools._harness_check)
    el_harness_seen = _safe(HarnessTools._harness_seen)
    el_harness_list = _safe(HarnessTools._harness_list)
