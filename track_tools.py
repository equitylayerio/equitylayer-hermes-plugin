"""One tracked object, three levels: what the agent sees.

Everything a person tracks is one kind of thing, a tracked item, at one of three levels:

  readings            curated readings for a sector, no view needed (a watchlist)
  your thesis         the person's own thesis and wrong_if (a harness), usually on top of readings with the
                      same id: the readings stay and become the thesis's evidence
  EquityLayer thesis  a published Research Pack the person follows (a Follow Card)

The stores stay as they are underneath. These tools give the model one way to save, check, mark as read and
list them, so it never has to pick between families of tools.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .follows import FOLLOW_ID_RE
from . import formatters
from .formatters import _table
from .harness_store import HARNESS_ID_RE, is_due, slugify
from .profile_store import FIELDS as PROFILE_FIELDS
from .watch_store import is_watch_due

logger = logging.getLogger(__name__)

READINGS, THESIS, PACK = "readings", "your thesis", "EquityLayer thesis"
NOTHING_NEW = "Nothing new across what you track. Hermes stays quiet until something moves or needs you."
NOTHING_TRACKED = "You don't track anything yet. Type `/equitylayer:start`."


def _text(args: dict, name: str) -> str:
    value = args.get(name)
    return value.strip() if isinstance(value, str) else ""


def _level(parts: dict) -> str:
    if "follow" in parts:
        return PACK
    return THESIS if "harness" in parts else READINGS


class TrackTools:
    """Mixin for EquityLayerTools; needs the harness, watch, follow and profile stores and their methods."""

    # -- where an id lives ---------------------------------------------------------------------------

    def _item_id(self, args: dict) -> tuple[str, dict | None]:
        """The id the model gave (item_id, or the older harness_id / watch_id), or an error."""
        for key in ("item_id", "harness_id", "watch_id", "follow_id"):
            value = args.get(key)
            if value is None or value == "":
                continue
            if not isinstance(value, str) or not (HARNESS_ID_RE.match(value.strip()) or FOLLOW_ID_RE.match(value.strip())):
                return "", {"ok": False, "error": "invalid_argument", "argument": key,
                            "message": "Give an id exactly as el_list shows it."}
            return value.strip(), None
        return "", None

    def _parts(self, item_id: str) -> dict:
        """Every stored part of one item. A thesis and its readings share an id."""
        parts: dict[str, dict] = {}
        if not item_id:
            return parts
        if FOLLOW_ID_RE.match(item_id):
            record = self._safe_get(self._store_factory().get, item_id)
            if record:
                parts["follow"] = record
                # A followed Pack's readings are its evidence: one item, two files.
                readings_id = record.get("readings_id")
                watch = self._safe_get(self._watch_store_factory().get, readings_id) if isinstance(readings_id, str) else None
                if watch:
                    parts["watch"] = watch
            return parts
        for kind, getter in (("harness", self._harness_store_factory().get), ("watch", self._watch_store_factory().get)):
            record = self._safe_get(getter, item_id)
            if record:
                parts[kind] = record
        follow_id = (parts.get("watch") or {}).get("follow_id")
        if isinstance(follow_id, str) and FOLLOW_ID_RE.match(follow_id):
            record = self._safe_get(self._store_factory().get, follow_id)
            if record:
                parts["follow"] = record
        return parts

    @staticmethod
    def _part_id(parts: dict, kind: str, item_id: str) -> str:
        """The file id of one part; a followed Pack and its readings have different file ids."""
        record = parts.get(kind) or {}
        return str(record.get("follow_id" if kind == "follow" else "id") or item_id)

    @staticmethod
    def _safe_get(getter: Callable[[str], Any], item_id: str) -> dict | None:
        try:
            record = getter(item_id)
        except (OSError, ValueError):
            logger.warning("EquityLayer item %s could not be read", item_id)
            return None
        return record if isinstance(record, dict) else None

    def _taken(self, item_id: str) -> bool:
        """An id is taken if any store has a file for it, readable or not."""
        return any((store.dir / f"{item_id}.json").exists()
                   for store in (self._harness_store_factory(), self._watch_store_factory()))

    def _unique_item_id(self, title: str) -> str:
        base = slugify(title, fallback="tracked")
        candidate, n = base, 2
        while self._taken(candidate):
            suffix = f"-{n}"
            candidate = base[: 48 - len(suffix)] + suffix
            n += 1
        return candidate

    def _unknown_item(self, item_id: str) -> dict:
        return {"ok": False, "error": "unknown_item", "item_id": item_id,
                "hint": "Run el_list (/el list) for the ids you track."}

    # -- profile ---------------------------------------------------------------------------------------

    def _profile(self, args: dict) -> dict:
        fields = {k: args[k] for k in PROFILE_FIELDS if args.get(k) is not None}
        return self._profile_save(fields) if fields else self._profile_get({})

    # -- save ------------------------------------------------------------------------------------------

    def _track(self, args: dict) -> dict:
        """Save, update or add a level to a tracked item. What is given decides the level."""
        if self._in_cron():
            return {"ok": False, "error": "not_in_scheduled_run",
                    "message": "A scheduled run never changes what the person tracks."}
        item_id, bad = self._item_id(args)
        if bad:
            return bad
        parts = self._parts(item_id)
        if item_id and not parts:
            return self._unknown_item(item_id)
        theme = _text(args, "theme") or None

        if _text(args, "pack_id") or _text(args, "thesis_id"):
            if item_id:
                return {"ok": False, "error": "invalid_argument",
                        "message": "Following a Research Pack creates its own item; leave item_id out."}
            result = self._follow_create({k: args[k] for k in ("pack_id", "thesis_id") if _text(args, k)})
            return {**result, "item_id": result.get("follow_id"), "level": PACK}

        if isinstance(args.get("harness"), dict):
            if "follow" in parts:
                return {"ok": False, "error": "invalid_argument", "item_id": item_id,
                        "message": "That id is a followed Research Pack. Add a thesis to readings, or save it as new."}
            harness = args["harness"]
            if "harness" in parts:
                result = self._harness_save({"harness": harness, "harness_id": item_id})
                target, attached = item_id, False
            elif "watch" in parts:
                # The readings stay; the thesis joins them under the same id and they become its evidence.
                result = self._harness_save({"harness": harness, "_new_id": item_id})
                target, attached = item_id, True
                theme = theme or parts["watch"].get("theme")
            else:
                target = self._unique_item_id(str(harness.get("title") or harness.get("hypothesis") or "thesis"))
                result = self._harness_save({"harness": harness, "_new_id": target})
                attached = False
            if result.get("ok"):
                self._harness_store_factory().set_theme(target, theme)
            self._refresh_dashboard()
            out = {**result, "item_id": result.get("harness_id") or target, "level": THESIS}
            if attached and result.get("ok"):
                out["readings_kept"] = True
                out["markdown"] = ("**Your thesis now sits on top of your readings** (same id). The readings stay "
                                   "and become its evidence.\n\n" + str(result.get("markdown") or ""))
            return out

        if args.get("variables"):
            if "follow" in parts:
                return {"ok": False, "error": "invalid_argument", "item_id": item_id,
                        "message": "That id is a followed Research Pack. Save readings as a new item."}
            watch_args = {k: args[k] for k in ("title", "variables", "theme") if args.get(k) is not None}
            if "watch" in parts:
                watch_args["watch_id"] = item_id
                watch_args.setdefault("title", parts["watch"].get("title"))
                watch_args.setdefault("theme", parts["watch"].get("theme"))
            elif "harness" in parts:
                # Readings added under a thesis: same id, so the thesis gets its evidence.
                watch_args["_new_id"] = item_id
                watch_args.setdefault("title", parts["harness"].get("title"))
                watch_args.setdefault("theme", parts["harness"].get("theme"))
            else:
                watch_args["_new_id"] = self._unique_item_id(str(args.get("title") or "readings"))
            result = self._watch_save(watch_args)
            level = THESIS if "harness" in parts else READINGS
            return {**result, "item_id": result.get("watch_id"), "level": level}

        return {"ok": False, "error": "missing_argument", "argument": "variables, harness or pack_id",
                "message": "Give variables (follow readings), harness (your thesis) or pack_id (a published Pack)."}

    # -- check -----------------------------------------------------------------------------------------

    def _run_kind(self, kind: str, call: Callable[[], dict]) -> tuple[int, list[str], str]:
        """Run one kind's check. Its errors count as something to report, and never hide the other kinds."""
        try:
            part = call()
        except Exception as exc:  # noqa: BLE001 - one kind must not stop the others
            logger.warning("EquityLayer %s check failed", kind, exc_info=True)
            return 1, [], f"Could not check your {kind}: {getattr(exc, 'code', type(exc).__name__)}. It will be tried again."
        if not part.get("ok"):
            return 1, [], f"Could not check your {kind}: {part.get('error')}. It will be tried again."
        if kind == "followed Research Packs":
            pending = [a.get("follow_id") for a in part.get("awaiting_review") or [] if isinstance(a, dict)]
            count = ((part.get("needs_review") or 0) + len(pending) + (part.get("errors") or 0)
                     + (part.get("unavailable_new") or 0))
            return count, [p for p in pending if p], str(part.get("markdown") or "")
        count = (part.get("report_total") or 0) + (part.get("errors") or 0)
        return count, list(part.get("awaiting_read") or []), str(part.get("markdown") or "")

    def _check(self, args: dict, *, seen: bool = False) -> dict:
        """Check one item, or everything that is due. `seen` is only set by a person's slash command."""
        item_id, bad = self._item_id(args)
        if bad:
            return bad
        calls: list[tuple[str, Callable[[], dict]]] = []
        if item_id:
            parts = self._parts(item_id)
            if not parts:
                return self._unknown_item(item_id)
            harness_id, watch_id, follow_id = (self._part_id(parts, k, item_id) for k in ("harness", "watch", "follow"))
            if "follow" in parts:  # the Pack first, then the readings that back it
                calls.append(("followed Research Packs", lambda: self._follow_check({"follow_id": follow_id})))
            if "harness" in parts:
                calls.append(("theses", lambda: self._harness_check({"harness_id": harness_id}, seen=seen)))
            if "watch" in parts:
                calls.append(("readings", lambda: self._watch_check({"watch_id": watch_id}, seen=seen)))
        else:
            if self._store_factory().all()[0]:  # same order as one item: the Pack, then its evidence
                calls.append(("followed Research Packs", lambda: self._follow_check({})))
            if self._harness_store_factory().all()[0]:
                calls.append(("theses", lambda: self._harness_check({}, seen=seen)))
            if self._watch_store_factory().all()[0]:
                calls.append(("readings", lambda: self._watch_check({}, seen=seen)))
        report_total, awaiting, blocks = 0, [], []
        for kind, call in calls:
            count, waiting, markdown = self._run_kind(kind, call)
            report_total += count
            awaiting += [w for w in waiting if w not in awaiting]
            if (count or item_id) and markdown:
                blocks.append(markdown)
        self._refresh_dashboard()
        follow_now = self._safe_get(self._store_factory().get, self._part_id(parts, "follow", item_id)) \
            if item_id and "follow" in parts else None
        summary = (follow_now or {}).get("pack") if not (follow_now or {}).get("unavailable_since") else None
        if isinstance(summary, dict):
            blocks.insert(0, formatters.format_pack_thesis(summary))
        if not calls:
            markdown = NOTHING_TRACKED
        else:
            markdown = "\n\n---\n\n".join(blocks) if blocks else NOTHING_NEW
        result = {"ok": True, "mode": "single" if item_id else "due", "report_total": report_total,
                  "awaiting_read": awaiting, "markdown": markdown}
        if item_id:
            result.update({"item_id": item_id, "level": _level(self._parts(item_id) or {"watch": {}})})
        return result

    # -- read ------------------------------------------------------------------------------------------

    def _seen(self, args: dict) -> dict:
        item_id, bad = self._item_id(args)
        if bad:
            return bad
        if not item_id:
            return {"ok": False, "error": "missing_argument", "argument": "item_id"}
        parts = self._parts(item_id)
        if not parts:
            return self._unknown_item(item_id)
        if "follow" in parts and args.get("accept_update"):
            # Moving to a new Pack version is an explicit choice, not the same as "I've read it".
            follow_id = self._part_id(parts, "follow", item_id)
            result = self._accept_next(follow_id)
            new_id = result.get("follow_id") or follow_id
            return {**result, "item_id": new_id, "previous_item_id": follow_id, "level": PACK}
        results = []
        if "harness" in parts:
            results.append(self._harness_seen({"harness_id": self._part_id(parts, "harness", item_id)}))
        if "watch" in parts:
            results.append(self._watch_seen({"watch_id": self._part_id(parts, "watch", item_id)}))
        pack_note, pack_ok = "", False
        pending = (parts.get("follow") or {}).get("pending_review")
        if "follow" in parts and isinstance(pending, dict):
            if pending.get("revision_changed"):
                pack_note = ("This Pack also has a new revision to review. It moves to it only when the person says "
                             "to accept it (el_seen with accept_update).")
            else:
                # New data for a reading it watches: reading it is the same as reading the readings.
                accepted = self._accept_next(self._part_id(parts, "follow", item_id))
                pack_ok = bool(accepted.get("ok"))
                pack_note = "The Pack's baseline moved to the new data." if pack_ok else ""
        elif "follow" in parts and not results:
            return {"ok": True, "item_id": item_id, "level": PACK,
                    "markdown": "Nothing to mark: this Pack has no update waiting."}
        done = [r for r in results if r.get("ok")]
        if not done and not pack_ok:
            first = results[0] if results else {"ok": False, "error": "accept_needs_confirmation",
                                                "message": pack_note}
            return {**first, "item_id": item_id, "level": _level(parts)}
        markdown = "\n\n".join([str(r.get("markdown") or "") for r in done if r.get("markdown")] + [pack_note])
        return {"ok": True, "item_id": item_id, "level": _level(parts),
                "markdown": markdown.strip() or f"Marked `{item_id}` as read."}

    # -- list ------------------------------------------------------------------------------------------

    def _list(self, args: dict) -> dict:
        item_id, bad = self._item_id(args)
        if bad:
            return bad
        if item_id:
            parts = self._parts(item_id)
            if not parts:
                return self._unknown_item(item_id)
            blocks = []
            if "follow" in parts:
                record = parts["follow"]
                summary = record.get("pack") if isinstance(record.get("pack"), dict) else None
                blocks.append(formatters.format_pack_thesis(summary) if summary else "")
                blocks.append(f"Following `{record.get('target_id')}` (next check {record.get('next_check_at') or 'unknown'}).")
            if "harness" in parts:
                blocks.append(str(self._harness_list({"harness_id": self._part_id(parts, "harness", item_id)}).get("markdown") or ""))
            if "watch" in parts:
                blocks.append(str(self._watch_list({"watch_id": self._part_id(parts, "watch", item_id)}).get("markdown") or ""))
            blocks = [b for b in blocks if b]
            return {"ok": True, "item_id": item_id, "level": _level(parts), "markdown": "\n\n---\n\n".join(blocks)}

        items: list[dict[str, Any]] = []
        harnesses, bad_h = self._harness_store_factory().all()
        watches, bad_w = self._watch_store_factory().all()
        watch_by_id = {w.get("id"): w for w in watches}
        for r in harnesses:
            last = r.get("last_check") if isinstance(r.get("last_check"), dict) else {}
            readings = watch_by_id.pop(r.get("id"), None)
            unread = isinstance(r.get("pending_baseline"), dict) or bool(readings and isinstance(readings.get("pending"), dict))
            state = "unread" if unread else ("due" if is_due(r) else "waiting")
            items.append({"id": r.get("id"), "title": r.get("title"),
                          "level": THESIS + (" + readings" if readings else ""),
                          "last_check": last.get("as_of") or "never", "state": state})
        follows, bad_f = self._store_factory().all()
        for r in follows:
            readings = watch_by_id.pop(r.get("readings_id"), None) if r.get("readings_id") else None
            unread = bool(readings and isinstance(readings.get("pending"), dict))
            state = ("not published" if r.get("unavailable_since") else "update to review" if r.get("pending_review")
                     else ("unread" if unread else "following"))
            items.append({"id": r.get("follow_id"), "title": (r.get("pack") or {}).get("title") or r.get("target_id"),
                          "level": PACK + (" + readings" if readings else ""),
                          "last_check": r.get("last_checked_at") or "never", "state": state})
        for r in watch_by_id.values():
            last = r.get("last_check") if isinstance(r.get("last_check"), dict) else {}
            state = "unread" if isinstance(r.get("pending"), dict) else ("due" if is_watch_due(r) else "waiting")
            items.append({"id": r.get("id"), "title": r.get("title"), "level": READINGS,
                          "last_check": last.get("as_of") or "never", "state": state})
        table = _table(["id", "title", "level", "last check", "state"],
                       [[i["id"], i["title"], i["level"], i["last_check"], i["state"]] for i in items])
        unreadable = len(bad_h or []) + len(bad_w or []) + len(bad_f or [])
        markdown = table if items else NOTHING_TRACKED
        if unreadable:
            markdown += f"\n\n{unreadable} local file(s) could not be read."
        return {"ok": True, "items": items, "markdown": markdown}

    # -- published research ----------------------------------------------------------------------------

    def _research_pack(self, args: dict) -> dict:
        action = _text(args, "action") or "list"
        if action == "list":
            return self._registry({"publisher": _text(args, "publisher")})
        if action == "read":
            return self._pack({"pack_id": _text(args, "pack_id"), "symbols": args.get("symbols") or []})
        if action == "scorecard":
            return self._scorecard({"id": _text(args, "pack_id") or _text(args, "id")})
        return {"ok": False, "error": "invalid_argument",
                "message": "action must be list, read or scorecard. To follow a Pack, use el_track with pack_id."}
