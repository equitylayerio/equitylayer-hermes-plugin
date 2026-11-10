"""Watchlist tools: follow a sector's curated readings without writing a thesis."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from .company_roles import role_for
from .formatters import _bullets, _join, _section, _table
from .harness_format import BOUNDARY, _attributions, _value
from .harness_store import TAIPEI, today_taipei
from .mcp_client import McpError
from .watch_store import RECENT_VALUES, WatchStore, is_watch_due, next_due_from, validate_variables

logger = logging.getLogger(__name__)

THEMES = ("optical_cpo", "space_infrastructure", "custom_asic", "physical_ai")
EVENT_LOOKBACK_DAYS = 45
MAX_EVENTS = 8


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


PERIOD_RE = re.compile(r"^(FY)?(\d{4})(?:-(Q[1-4]|\d{2}))?$")


def _period_index(period: Any) -> tuple[str, int] | None:
    """('M', months) / ('Q', quarters) / ('Y', years) for YYYY-MM, [FY]YYYY-Qn and [FY]YYYY periods."""
    match = PERIOD_RE.match(str(period or ""))
    if not match:
        return None
    fiscal, year, part = match.group(1) or "", int(match.group(2)), match.group(3)
    if part is None:
        return (fiscal + "Y", year)
    if part.startswith("Q"):
        return (fiscal + "Q", year * 4 + int(part[1]) - 1)
    return ("M", year * 12 + int(part) - 1)


def _adjacent(previous: Any, latest: Any) -> bool:
    a, b = _period_index(previous), _period_index(latest)
    return bool(a and b and a[0] == b[0] and b[1] - a[1] == 1)


def _change(latest: dict | None, previous: dict | None, period_basis: Any = "discrete") -> str:
    """Year-to-date figures and periods that do not follow on are never compared."""
    if period_basis not in (None, "discrete"):
        return ""
    if not _adjacent((previous or {}).get("period"), (latest or {}).get("period")):
        return ""
    a, b = _number((latest or {}).get("value")), _number((previous or {}).get("value"))
    if a is None or b is None or b == 0:
        return ""
    return f"{(a / b - 1) * 100:+.1f}% vs {previous.get('period')}"


def _row(variable: str, data: dict, seen_period: str | None) -> dict:
    readings = [r for r in data.get("readings") or [] if isinstance(r, dict)]
    latest = readings[-1] if readings else None
    previous = readings[-2] if len(readings) > 1 else None
    withheld = bool(latest and latest.get("withheld"))
    period = latest.get("period") if latest else None
    discrete = data.get("period_basis") in (None, "discrete")
    return {
        "variable": variable,
        "name": data.get("name") or variable,
        "period_basis": data.get("period_basis"),
        "chain_position": data.get("chain_position"),
        "category": data.get("category"),
        "company": role_for(data.get("entity")),
        "entity": data.get("entity"),
        "unit": data.get("unit"),
        "cadence": data.get("cadence"),
        "caveat": data.get("caveat"),
        "next_reading": data.get("next_reading"),
        "latest": {"period": period, "value": None if withheld else (latest or {}).get("value"),
                   "withheld": (latest or {}).get("withheld")} if latest else None,
        "previous": {"period": previous.get("period"), "value": previous.get("value")} if previous else None,
        "change": "" if withheld else _change(latest, previous, data.get("period_basis")),
        "recent": [r.get("value") for r in readings if _number(r.get("value")) is not None][-RECENT_VALUES:]
        if discrete else [],
        "new": bool(period) and not withheld and period != seen_period,
        "source_url": (latest or {}).get("source_url") or (data.get("source") or {}).get("url"),
        "attribution": [a for a in data.get("attribution") or [] if isinstance(a, str)],
    }


def _unavailable_row(variable: str, error: McpError) -> dict:
    return {"variable": variable, "name": variable, "unit": None, "caveat": None, "next_reading": None,
            "latest": None, "previous": None, "change": "", "recent": [], "new": False, "attribution": [],
            "error": error.code}


def format_watch(record: dict, check: dict, *, seen: bool) -> str:
    rows = check.get("rows") or []
    first = check.get("first_check")
    new_rows = [r for r in rows if r.get("new")]
    table = _table(
        ["", "reading", "latest", "change", "what it can't show"],
        [["●" if r.get("new") else "", r.get("name"),
          (f"unavailable ({r['error']})" if r.get("error") else
           f"{r['latest']['period']}: withheld ({str(r['latest']['withheld']).replace('_', ' ')})"
           if r.get("latest") and r["latest"].get("withheld")
           else f"{(r.get('latest') or {}).get('period') or '—'}: {_value((r.get('latest') or {}).get('value'), r.get('unit'))}"),
          r.get("change") or "", r.get("caveat") or ""] for r in rows],
    ) if rows else "No readings."
    if first:
        lead = "First check of this watchlist: these are the latest readings."
    elif new_rows:
        lead = f"**New since you last read:** {len(new_rows)} reading(s), marked ●."
    else:
        lead = "Nothing new since you last read."
    events = _bullets(
        f"{e.get('at')} · {e.get('title')}"
        for e in check.get("events") or []
    )
    upcoming = _bullets(f"{u.get('date')} · {u.get('names')}: {u.get('reason')}" for u in check.get("upcoming") or [])
    read_line = ("Saved as read." if seen else
                 f"Say \"I've read it\" (or run `/el watch-seen {record.get('id')}`) and it becomes what the next check compares with.")
    return _join(
        f"## Watchlist: {record.get('title')}",
        f"As of {check.get('as_of')} · next check {check.get('next_due')}",
        lead,
        table,
        _section("Recent events", events) if events else "",
        _section("Coming up", upcoming) if upcoming else "",
        _section("Sources", _bullets(_attributions(r.get("attribution") for r in rows))),
        "Full sources and links are on your dashboard.",
        read_line if (first or new_rows or check.get("events_new")) else "",
        BOUNDARY,
    )


class WatchTools:
    """Mixin for EquityLayerTools. Needs _call, _call_full, _in_cron and _watch_store_factory."""

    def _watch_store(self) -> WatchStore:
        return self._watch_store_factory()

    def _watch_save(self, args: dict) -> dict:
        variables = validate_variables(args.get("variables"))
        theme = args.get("theme") or None
        if theme is not None and theme not in THEMES:
            raise ValueError(f"theme must be one of: {', '.join(THEMES)}")
        title = " ".join(str(args.get("title") or "").split())[:80]
        if not title:
            return {"ok": False, "error": "missing_argument", "argument": "title",
                    "message": "Give the watchlist a short title, for example \"CPO curated readings\"."}
        names = {}
        for variable in variables:  # every id must be one EquityLayer serves
            data = self._call("get_variable", {"variable": variable})
            names[variable] = data.get("name") or variable
        store = self._watch_store()
        watch_id = args.get("watch_id") or store.unique_id(title)
        if args.get("watch_id") and store.get(watch_id) is None:
            return {"ok": False, "error": "unknown_watchlist", "watch_id": watch_id,
                    "hint": "Omit watch_id to create a new watchlist."}
        record, created = store.save(watch_id, title, variables, theme)
        lines = [f"**{'Saved' if created else 'Updated'} watchlist `{watch_id}`** on this machine: {title}", ""]
        lines += [f"- {names[v]}" for v in variables]
        lines += ["", "Nothing is sent to EquityLayer except the variable ids when it checks."]
        return {"ok": True, "watch_id": watch_id, "created": created, "markdown": "\n".join(lines),
                "stored": "local only"}

    def _events_for(self, variables: list[str], since: str) -> list[dict]:
        found: dict[str, dict] = {}
        for variable in variables:
            try:
                data = self._call_full("list_research_events", {"variable": variable, "since": since, "limit": 5})
            except McpError as exc:
                logger.info("EquityLayer events unavailable for %s: %s", variable, exc.code)
                continue
            for event in data.get("events") or []:
                if isinstance(event, dict) and isinstance(event.get("id"), str):
                    source = event.get("source") if isinstance(event.get("source"), dict) else {}
                    url = source.get("url") if str(source.get("url") or "").startswith("https://") else None
                    found[event["id"]] = {"id": event["id"], "at": event.get("at"), "title": event.get("title"),
                                          "type": event.get("type"), "url": url}
        return sorted(found.values(), key=lambda e: str(e.get("at") or ""), reverse=True)[:MAX_EVENTS]

    def _upcoming_for(self, variables: list[str], names: dict[str, str]) -> list[dict]:
        try:
            data = self._call_full("list_upcoming_triggers", {"variables": variables, "limit": 10})
        except McpError as exc:
            logger.info("EquityLayer upcoming triggers unavailable: %s", exc.code)
            return []
        out = []
        for trigger in data.get("triggers") or []:
            if isinstance(trigger, dict):
                ids = [v for v in trigger.get("variables") or [] if v in names]
                out.append({"date": trigger.get("date"), "reason": trigger.get("reason"),
                            "names": ", ".join(names[v] for v in ids) or "a tracked reading"})
        return out[:6]

    def _run_watch(self, store: WatchStore, record: dict, mark_seen: bool) -> dict:
        seen = record.get("seen") if isinstance(record.get("seen"), dict) else None
        periods = (seen or {}).get("periods") or {}
        rows = []
        for variable in record["variables"]:
            try:
                rows.append(_row(variable, self._call("get_variable", {"variable": variable}), periods.get(variable)))
            except McpError as exc:
                rows.append(_unavailable_row(variable, exc))
        names = {r["variable"]: r["name"] for r in rows}
        today = today_taipei()
        since = (datetime.now(TAIPEI).date() - timedelta(days=EVENT_LOOKBACK_DAYS)).isoformat()
        events = self._events_for(record["variables"], since)
        seen_events = set((seen or {}).get("events") or [])
        events_new = [e for e in events if e["id"] not in seen_events]
        check = {
            "as_of": today,
            "first_check": seen is None,
            "rows": rows,
            "new_count": sum(1 for r in rows if r["new"]),
            "events": events,
            "events_new": len(events_new),
            "upcoming": self._upcoming_for(record["variables"], names),
            "next_due": next_due_from(rows),
        }
        report = check["first_check"] or check["new_count"] > 0 or check["events_new"] > 0
        snapshot = {"as_of": today, "periods": {r["variable"]: (r.get("latest") or {}).get("period") or periods.get(r["variable"])
                                               for r in rows},
                    "events": [e["id"] for e in events]}
        saved = mark_seen or not report  # nothing new advances on its own
        store.record_check(record["id"], check, snapshot, seen=saved)
        return {"watch_id": record["id"], "report": report, "baseline_saved": saved,
                "markdown": format_watch(record, check, seen=saved)}

    def _watch_check(self, args: dict, *, seen: bool = False) -> dict:
        store = self._watch_store()
        watch_id = args.get("watch_id")
        if watch_id:
            record = store.get(watch_id)
            if record is None:
                return {"ok": False, "error": "unknown_watchlist", "watch_id": watch_id,
                        "hint": "Run el_watch_list (/el watches) for saved ids."}
            targets = [record]
        else:
            records, _ = store.all()
            targets = [r for r in records if isinstance(r.get("pending"), dict) or is_watch_due(r)]
        mark_seen = seen and not self._in_cron()
        checked = []
        for record in targets:
            try:
                checked.append(self._run_watch(store, record, mark_seen))
            except Exception as exc:  # noqa: BLE001 - one watchlist must not stop the others
                logger.warning("EquityLayer watchlist %s not checked", record.get("id"), exc_info=True)
                checked.append({"watch_id": record.get("id"), "ok": False, "report": False, "baseline_saved": False,
                                "markdown": f"Watchlist `{record.get('id')}` could not be checked: "
                                            f"{getattr(exc, 'code', type(exc).__name__)}. It will be tried again."})
        blocks = [c["markdown"] for c in checked if c["report"] or watch_id or c.get("ok") is False]
        self._refresh_dashboard()
        return {
            "ok": True,
            "mode": "single" if watch_id else "due",
            "checked": [c["watch_id"] for c in checked],
            "report_total": sum(1 for c in checked if c["report"]),
            "errors": sum(1 for c in checked if c.get("ok") is False),
            "awaiting_read": [c["watch_id"] for c in checked if c["report"] and not c["baseline_saved"]],
            "markdown": "\n\n---\n\n".join(blocks) if blocks else "No watchlist has anything new.",
        }

    def _watch_seen(self, args: dict) -> dict:
        if self._in_cron():
            return {"ok": False, "error": "not_in_scheduled_run",
                    "message": "A scheduled run never marks a watchlist as read. The person does."}
        watch_id = args.get("watch_id")
        if not watch_id:
            return {"ok": False, "error": "missing_argument", "argument": "watch_id"}
        record = self._watch_store().mark_seen(watch_id)
        self._refresh_dashboard()
        if record is None:
            return {"ok": True, "watch_id": watch_id, "markdown": "Nothing was waiting to be read."}
        return {"ok": True, "watch_id": watch_id,
                "markdown": f"Marked `{watch_id}` as read. The next check reports only what is new after this."}

    def _watch_list(self, args: dict) -> dict:
        store = self._watch_store()
        watch_id = args.get("watch_id")
        if watch_id:
            record = store.get(watch_id)
            if record is None:
                return {"ok": False, "error": "unknown_watchlist", "watch_id": watch_id}
            last = record.get("last_check")
            text = format_watch(record, last, seen=not isinstance(record.get("pending"), dict)) if isinstance(last, dict) \
                else f"## Watchlist: {record.get('title')}\n\nNot checked yet."
            return {"ok": True, "watchlist": {k: record.get(k) for k in ("id", "title", "theme", "variables")},
                    "markdown": text}
        records, unreadable = store.all()
        rows = [[r.get("id"), r.get("title"), len(r.get("variables") or []),
                 (r.get("last_check") or {}).get("as_of") or "never",
                 "unread" if isinstance(r.get("pending"), dict) else ("due" if is_watch_due(r) else "waiting")]
                for r in records]
        text = _table(["id", "title", "readings", "last check", "state"], rows) if rows else "No watchlist saved yet."
        if unreadable:
            text += f"\n\n{len(unreadable)} file(s) could not be read: {', '.join(unreadable)}"
        return {"ok": True, "watchlists": [{"id": r.get("id"), "title": r.get("title")} for r in records],
                "markdown": text}

    def _watch_remove(self, args: dict) -> dict:
        watch_id = args.get("watch_id")
        if not watch_id:
            return {"ok": False, "error": "missing_argument", "argument": "watch_id"}
        removed = self._watch_store().delete(watch_id)
        self._refresh_dashboard()
        return {"ok": True, "removed": removed,
                "markdown": f"Removed `{watch_id}` from this machine." if removed else f"No watchlist `{watch_id}`."}
