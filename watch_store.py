"""Local watchlists: the curated readings a person follows without writing a thesis.

A watchlist is a short list of EquityLayer variables for one sector. Each check reads their latest
values and reports new periods, recent events and what is due next. Like a harness, nothing becomes
"read" until the person says so. One JSON file per watchlist, replaced atomically.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .harness_store import HARNESS_ID_RE, HISTORY_LIMIT, PLUGIN_NAME, TAIPEI, slugify, today_taipei

VARIABLE_RE = re.compile(r"^v:[a-z0-9]+(?:\.[a-z0-9_]+){2,5}$")
MAX_VARIABLES = 8
RECENT_VALUES = 12


def default_watch_store() -> "WatchStore":
    from plugins.plugin_storage import plugin_data_dir

    return WatchStore(Path(plugin_data_dir(PLUGIN_NAME)))


def validate_variables(variables: Any) -> list[str]:
    if isinstance(variables, str):
        variables = [variables]
    if not isinstance(variables, list) or not 1 <= len(variables) <= MAX_VARIABLES:
        raise ValueError(f"variables must be a list of 1 to {MAX_VARIABLES} EquityLayer variable ids")
    clean: list[str] = []
    for variable in variables:
        if not isinstance(variable, str) or not VARIABLE_RE.match(variable):
            raise ValueError(f"Not an EquityLayer variable id: {variable!r}")
        if variable not in clean:
            clean.append(variable)
    return clean


def is_watch_due(record: dict, now: datetime | None = None) -> bool:
    last = record.get("last_check")
    if not isinstance(last, dict):
        return True
    due = last.get("next_due")
    if not isinstance(due, str):
        return True
    return due[:10] <= today_taipei(now)


def next_due_from(rows: list[dict], now: datetime | None = None) -> str:
    """The earliest next reading at or after today; tomorrow when none is known."""
    today = today_taipei(now)
    dates = sorted(r["next_reading"] for r in rows if isinstance(r.get("next_reading"), str) and r["next_reading"] >= today)
    if dates:
        return dates[0][:10]
    return ((now or datetime.now(TAIPEI)).astimezone(TAIPEI).date() + timedelta(days=1)).isoformat()


class WatchStore:
    def __init__(self, root: Path):
        self.dir = Path(root) / "watchlists"
        self._lock = threading.Lock()

    def get(self, watch_id: str) -> dict | None:
        path = self._path(watch_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def all(self) -> tuple[list[dict], list[str]]:
        records: list[dict] = []
        unreadable: list[str] = []
        if not self.dir.is_dir():
            return records, unreadable
        for path in sorted(self.dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                validate_variables(record.get("variables"))
                records.append(record)
            except (OSError, ValueError, AttributeError):
                unreadable.append(path.name)
        return records, unreadable

    def unique_id(self, title: str) -> str:
        base = slugify(title, fallback="watchlist")
        candidate, n = base, 2
        while self._path(candidate).exists():
            suffix = f"-{n}"
            candidate = base[: 48 - len(suffix)] + suffix
            n += 1
        return candidate

    def save(self, watch_id: str, title: str, variables: list[str], theme: str | None,
             now: datetime | None = None) -> tuple[dict, bool]:
        stamp = today_taipei(now)
        existing = self.get(watch_id)
        if existing:
            existing.update({"title": title, "variables": variables, "theme": theme, "updated_at": stamp})
            if isinstance(existing.get("last_check"), dict):
                existing["last_check"]["next_due"] = None
            record, created = existing, False
        else:
            record = {"id": watch_id, "title": title, "theme": theme, "variables": variables,
                      "created_at": stamp, "updated_at": stamp, "seen": None, "pending": None,
                      "last_check": None, "history": []}
            created = True
        self._write(self._path(watch_id), record)
        return record, created

    def record_check(self, watch_id: str, check: dict, snapshot: dict, *, seen: bool) -> dict:
        record = self.get(watch_id)
        if record is None:
            raise KeyError(watch_id)
        record["last_check"] = check
        summary = {"as_of": check.get("as_of"), "new": check.get("new_count", 0),
                   "events": len(check.get("events") or []), "next_due": check.get("next_due")}
        record["history"] = ([summary] + list(record.get("history") or []))[:HISTORY_LIMIT]
        if seen:
            record["seen"], record["pending"] = snapshot, None
        else:
            record["pending"] = snapshot
        self._write(self._path(watch_id), record)
        return record

    def mark_seen(self, watch_id: str) -> dict | None:
        record = self.get(watch_id)
        if record is None:
            raise KeyError(watch_id)
        if not isinstance(record.get("pending"), dict):
            return None
        record["seen"], record["pending"] = record["pending"], None
        self._write(self._path(watch_id), record)
        return record

    def link_follow(self, watch_id: str, follow_id: str | None) -> None:
        """Mark a watchlist as the readings a followed Research Pack watches (same tracked item)."""
        record = self.get(watch_id)
        if record is None:
            raise KeyError(watch_id)
        record["follow_id"] = follow_id
        self._write(self._path(watch_id), record)

    def delete(self, watch_id: str) -> bool:
        path = self._path(watch_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _path(self, watch_id: Any) -> Path:
        if not isinstance(watch_id, str) or not HARNESS_ID_RE.match(watch_id):
            raise ValueError(f"Invalid watchlist id: {watch_id!r}")
        return self.dir / f"{watch_id}.json"

    def _write(self, path: Path, data: dict) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, indent=2)
                os.replace(tmp, path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
