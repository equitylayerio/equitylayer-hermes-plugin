"""Local storage for the caller's own thesis harnesses and baselines.

EquityLayer stores neither the harness nor the baseline, so this machine is the only copy.
One JSON file per harness, replaced atomically.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PLUGIN_NAME = "equitylayer"
HARNESS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
HISTORY_LIMIT = 30
# EquityLayer dates its readings and due dates on Taipei calendar days.
TAIPEI = timezone(timedelta(hours=8))
STATUSES = ("not_due", "seen", "against", "late", "no_data")


def default_harness_store() -> "HarnessStore":
    from plugins.plugin_storage import plugin_data_dir

    return HarnessStore(Path(plugin_data_dir(PLUGIN_NAME)))


def today_taipei(now: datetime | None = None) -> str:
    return (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date().isoformat()


def slugify(text: str, fallback: str = "thesis") -> str:
    """A short, file-safe id from a title. Non-ASCII titles fall back to `fallback`."""
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", ascii_text.lower())
    slug = "-".join(words)[:48].strip("-")
    return slug or fallback


def next_due_date(check: dict | None) -> str | None:
    """`next_due` is an object ({date, kind, ref}) on the wire; older shapes may be a bare date."""
    if not isinstance(check, dict):
        return None
    due = check.get("next_due")
    if isinstance(due, dict):
        due = due.get("date")
    return due if isinstance(due, str) and len(due) >= 10 else None


def is_due(record: dict, now: datetime | None = None) -> bool:
    """Never checked, or the next due date has arrived. A missing date counts as due."""
    last = record.get("last_check")
    if not isinstance(last, dict):
        return True
    due = last.get("next_due")
    if not isinstance(due, str):
        return True
    return due[:10] <= today_taipei(now)


def summarize_check(result: dict) -> dict:
    """The small part of a check worth keeping in history: counts, not readings."""
    links = [link for link in result.get("links") or [] if isinstance(link, dict)]
    counts = {status: 0 for status in STATUSES}
    for link in links:
        status = link.get("status")
        if status in counts:
            counts[status] += 1
    fired = [
        w.get("id") for w in result.get("wrong_if") or [] if isinstance(w, dict) and w.get("result") == "fired"
    ]
    changed = result.get("changed") if isinstance(result.get("changed"), dict) else {}
    return {
        "as_of": result.get("as_of"),
        "links": {link.get("id"): link.get("status") for link in links},
        "counts": counts,
        "wrong_if_fired": fired,
        "needs_human": len(result.get("needs_human") or []),
        "variables_changed": len(changed.get("variables") or []),
        "next_due": next_due_date(result),
    }


class HarnessStore:
    def __init__(self, root: Path):
        self.dir = Path(root) / "harnesses"
        self._lock = threading.Lock()

    # -- reads -----------------------------------------------------------------------------------

    def get(self, harness_id: str) -> dict | None:
        path = self._path(harness_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def all(self) -> tuple[list[dict], list[str]]:
        """Return (records, unreadable file names). One bad file must not hide the others."""
        records: list[dict] = []
        unreadable: list[str] = []
        if not self.dir.is_dir():
            return records, unreadable
        for path in sorted(self.dir.glob("*.json")):
            if path.name.startswith("."):
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record.get("harness"), dict):
                    raise ValueError("record has no harness")
                records.append(record)
            except (OSError, ValueError, AttributeError):
                unreadable.append(path.name)
        records.sort(key=lambda r: (str((r.get("last_check") or {}).get("next_due") or ""), str(r.get("id"))))
        return records, unreadable

    def unique_id(self, title: str) -> str:
        base = slugify(title)
        candidate, n = base, 2
        while self._path(candidate).exists():
            suffix = f"-{n}"
            candidate = base[: 48 - len(suffix)] + suffix
            n += 1
        return candidate

    # -- writes ----------------------------------------------------------------------------------

    def save_harness(self, harness_id: str, harness: dict, now: datetime | None = None) -> tuple[dict, bool]:
        """Create or replace the harness text. The baseline and history are kept on replace."""
        stamp = today_taipei(now)
        existing = self.get(harness_id)
        if existing:
            existing["harness"] = harness
            existing["title"] = harness.get("title") or existing.get("title")
            existing["updated_at"] = stamp
            record, created = existing, False
        else:
            record = {
                "id": harness_id,
                "title": harness.get("title") or harness_id,
                "created_at": stamp,
                "updated_at": stamp,
                "harness": harness,
                "baseline": None,
                "pending_baseline": None,
                "last_check": None,
                "history": [],
            }
            created = True
        self._write(self._path(harness_id), record)
        return record, created

    def record_check(self, harness_id: str, result: dict, *, seen: bool) -> dict:
        """Keep a check's summary. `next_baseline` becomes the baseline only once a person has seen it."""
        record = self.get(harness_id)
        if record is None:
            raise KeyError(harness_id)
        summary = summarize_check(result)
        record["last_check"] = summary
        record["history"] = ([summary] + list(record.get("history") or []))[:HISTORY_LIMIT]
        next_baseline = result.get("next_baseline")
        if isinstance(next_baseline, dict):
            if seen:
                record["baseline"] = next_baseline
                record["pending_baseline"] = None
            else:
                record["pending_baseline"] = next_baseline
        self._write(self._path(harness_id), record)
        return record

    def mark_seen(self, harness_id: str) -> dict | None:
        """Promote the pending baseline. Returns None when nothing was pending."""
        record = self.get(harness_id)
        if record is None:
            raise KeyError(harness_id)
        pending = record.get("pending_baseline")
        if not isinstance(pending, dict):
            return None
        record["baseline"] = pending
        record["pending_baseline"] = None
        self._write(self._path(harness_id), record)
        return record

    def delete(self, harness_id: str) -> bool:
        path = self._path(harness_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    # -- internals -------------------------------------------------------------------------------

    def _path(self, harness_id: Any) -> Path:
        # The id becomes a file name, so it must stay a plain slug.
        if not isinstance(harness_id, str) or not HARNESS_ID_RE.match(harness_id):
            raise ValueError(f"Invalid harness id: {harness_id!r}")
        return self.dir / f"{harness_id}.json"

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
