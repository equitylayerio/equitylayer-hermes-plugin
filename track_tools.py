"""One tracked object, three levels: what the agent sees.

Everything a person tracks is one kind of thing, a tracked item, at one of three levels:

  readings          curated readings for a sector, no view needed (stored as a watchlist)
  your thesis       the same readings plus the person's own thesis and wrong_if (stored as a harness)
  EquityLayer thesis  a published Research Pack the person follows (stored as a Follow Card)

The three stores stay as they are underneath. These tools give the model one way to save, check, mark as
read and list them, so it never has to pick between three families of tools.
"""

from __future__ import annotations

from typing import Any

from .follows import FOLLOW_ID_RE
from .formatters import _table
from .harness_store import HARNESS_ID_RE, is_due, slugify
from .profile_store import FIELDS as PROFILE_FIELDS
from .watch_store import is_watch_due

LEVELS = {"watch": "readings", "harness": "your thesis", "follow": "EquityLayer thesis"}
NOTHING_NEW = "Nothing new across what you track. Hermes stays quiet until something moves or needs you."


def _text(args: dict, name: str) -> str:
    value = args.get(name)
    return value.strip() if isinstance(value, str) else ""


class TrackTools:
    """Mixin for EquityLayerTools; needs the harness, watch, follow and profile stores and their methods."""

    # -- where an id lives ---------------------------------------------------------------------------

    def _locate(self, item_id: str) -> tuple[str, dict] | None:
        if not item_id:
            return None
        if FOLLOW_ID_RE.match(item_id):
            record = self._store_factory().get(item_id)
            return ("follow", record) if record else None
        if not HARNESS_ID_RE.match(item_id):
            return None
        record = self._harness_store_factory().get(item_id)
        if record:
            return "harness", record
        record = self._watch_store_factory().get(item_id)
        if record:
            return "watch", record
        return None

    def _unique_item_id(self, title: str) -> str:
        base = slugify(title, fallback="tracked")
        candidate, n = base, 2
        while self._locate(candidate):
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
        """Save or upgrade a tracked item. The level follows from what is given."""
        item_id = _text(args, "item_id")
        found = self._locate(item_id) if item_id else None
        if item_id and not found and (args.get("variables") or args.get("harness")) and not args.get("new"):
            return self._unknown_item(item_id)

        if _text(args, "pack_id") or _text(args, "thesis_id"):
            result = self._follow_create({k: args[k] for k in ("pack_id", "thesis_id") if _text(args, k)})
            return {**result, "item_id": result.get("follow_id"), "level": LEVELS["follow"]}

        if isinstance(args.get("harness"), dict):
            if found and found[0] == "harness":
                result = self._harness_save({"harness": args["harness"], "harness_id": item_id})
                upgraded = False
            elif found and found[0] == "watch":
                # Upgrade: the readings get the person's thesis on top, under the same id.
                result = self._harness_save({"harness": args["harness"], "_new_id": item_id})
                upgraded = bool(result.get("ok"))
                if upgraded:
                    self._watch_store_factory().delete(item_id)
            else:
                title = str(args["harness"].get("title") or args["harness"].get("hypothesis") or "thesis")
                result = self._harness_save({"harness": args["harness"], "_new_id": self._unique_item_id(title)})
                upgraded = False
            self._refresh_dashboard()
            out = {**result, "item_id": result.get("harness_id"), "level": LEVELS["harness"]}
            if upgraded:
                out["upgraded_from"] = LEVELS["watch"]
                out["markdown"] = ("**Your readings now carry your thesis** under the same id. "
                                   "The next check reads them against it.\n\n" + str(result.get("markdown") or ""))
            return out

        if args.get("variables"):
            watch_args = {k: args[k] for k in ("title", "variables", "theme") if args.get(k) is not None}
            if found and found[0] == "watch":
                watch_args["watch_id"] = item_id
            else:
                watch_args["_new_id"] = self._unique_item_id(str(args.get("title") or "readings"))
            result = self._watch_save(watch_args)
            return {**result, "item_id": result.get("watch_id"), "level": LEVELS["watch"]}

        return {"ok": False, "error": "missing_argument", "argument": "variables, harness or pack_id",
                "message": "Give variables (follow readings), harness (your thesis) or pack_id (a published Pack)."}

    # -- check -----------------------------------------------------------------------------------------

    def _check(self, args: dict, *, seen: bool = False) -> dict:
        """Check one item, or everything that is due. `seen` is only set by a person's slash command."""
        item_id = _text(args, "item_id")
        if item_id:
            found = self._locate(item_id)
            if not found:
                return self._unknown_item(item_id)
            kind = found[0]
            if kind == "harness":
                part = self._harness_check({"harness_id": item_id}, seen=seen)
            elif kind == "watch":
                part = self._watch_check({"watch_id": item_id}, seen=seen)
            else:
                part = self._follow_check({"follow_id": item_id})
            return {**part, "item_id": item_id, "level": LEVELS[kind],
                    "report_total": part.get("report_total", part.get("needs_review", 0))}

        parts: list[tuple[str, dict]] = []
        harnesses, _ = self._harness_store_factory().all()
        if harnesses:
            parts.append(("harness", self._harness_check({}, seen=seen)))
        watches, _ = self._watch_store_factory().all()
        if watches:
            parts.append(("watch", self._watch_check({}, seen=seen)))
        follows, _ = self._store_factory().all()
        if follows:
            parts.append(("follow", self._follow_check({})))
        report_total = 0
        awaiting: list[str] = []
        blocks = []
        for kind, part in parts:
            if not part.get("ok"):
                blocks.append(f"Could not check your {LEVELS[kind]} items: {part.get('error')}.")
                continue
            count = part.get("report_total", part.get("needs_review", 0)) or 0
            report_total += count
            awaiting += list(part.get("awaiting_read") or [])
            awaiting += [a.get("follow_id") for a in part.get("awaiting_review") or [] if isinstance(a, dict)]
            if count:
                blocks.append(str(part.get("markdown") or ""))
        if not parts:
            blocks.append("You don't track anything yet. Type `/equitylayer:start`.")
        self._refresh_dashboard()
        return {
            "ok": True,
            "mode": "due",
            "report_total": report_total,
            "awaiting_read": [a for a in awaiting if a],
            "markdown": "\n\n---\n\n".join(b for b in blocks if b) if blocks else NOTHING_NEW,
        }

    # -- read ------------------------------------------------------------------------------------------

    def _seen(self, args: dict) -> dict:
        item_id = _text(args, "item_id")
        found = self._locate(item_id)
        if not found:
            return self._unknown_item(item_id) if item_id else {"ok": False, "error": "missing_argument",
                                                                 "argument": "item_id"}
        kind = found[0]
        if kind == "harness":
            result = self._harness_seen({"harness_id": item_id})
        elif kind == "watch":
            result = self._watch_seen({"watch_id": item_id})
        else:
            result = self._accept_next(item_id)
        return {**result, "item_id": item_id, "level": LEVELS[kind]}

    # -- list ------------------------------------------------------------------------------------------

    def _list(self, args: dict) -> dict:
        item_id = _text(args, "item_id")
        if item_id:
            found = self._locate(item_id)
            if not found:
                return self._unknown_item(item_id)
            kind = found[0]
            if kind == "harness":
                result = self._harness_list({"harness_id": item_id})
            elif kind == "watch":
                result = self._watch_list({"watch_id": item_id})
            else:
                record = found[1]
                result = {"ok": True, "markdown": f"Following `{record.get('target_id')}` "
                                                  f"(next check {record.get('next_check_at') or 'unknown'})."}
            return {**result, "item_id": item_id, "level": LEVELS[kind]}

        items: list[dict[str, Any]] = []
        harnesses, bad_h = self._harness_store_factory().all()
        for r in harnesses:
            last = r.get("last_check") if isinstance(r.get("last_check"), dict) else {}
            state = "unread" if isinstance(r.get("pending_baseline"), dict) else ("due" if is_due(r) else "waiting")
            items.append({"id": r.get("id"), "title": r.get("title"), "level": LEVELS["harness"],
                          "last_check": last.get("as_of") or "never", "state": state})
        watches, bad_w = self._watch_store_factory().all()
        for r in watches:
            last = r.get("last_check") if isinstance(r.get("last_check"), dict) else {}
            state = "unread" if isinstance(r.get("pending"), dict) else ("due" if is_watch_due(r) else "waiting")
            items.append({"id": r.get("id"), "title": r.get("title"), "level": LEVELS["watch"],
                          "last_check": last.get("as_of") or "never", "state": state})
        follows, bad_f = self._store_factory().all()
        for r in follows:
            items.append({"id": r.get("follow_id"), "title": r.get("target_id"), "level": LEVELS["follow"],
                          "last_check": r.get("last_checked_at") or "never",
                          "state": "needs review" if r.get("pending_review") else "following"})
        table = _table(["id", "title", "level", "last check", "state"],
                       [[i["id"], i["title"], i["level"], i["last_check"], i["state"]] for i in items])
        unreadable = len(bad_h or []) + len(bad_w or []) + len(bad_f or [])
        markdown = table if items else "You don't track anything yet. Type `/equitylayer:start`."
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
