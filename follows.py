"""Local storage for caller-owned Follow Cards. EquityLayer does not store them."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PLUGIN_NAME = "equitylayer"
FOLLOW_ID_RE = re.compile(r"^follow_[a-f0-9]{32}$")
# EquityLayer publishes freshness as Taipei calendar dates.
TAIPEI = timezone(timedelta(hours=8))


def default_store() -> "FollowStore":
    from plugins.plugin_storage import plugin_data_dir

    return FollowStore(Path(plugin_data_dir(PLUGIN_NAME)))


def today_taipei(now: datetime | None = None) -> str:
    return (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date().isoformat()


def is_due(next_check_at: Any, now: datetime | None = None) -> bool:
    """A card with no usable date counts as due, so it is checked rather than forgotten."""
    if not isinstance(next_check_at, str) or len(next_check_at) < 10:
        return True
    return next_check_at[:10] <= today_taipei(now)


def target_of(card: dict) -> tuple[str, str] | None:
    if card.get("pack_id"):
        return "pack", str(card["pack_id"])
    if card.get("thesis_id"):
        return "view", str(card["thesis_id"])
    return None


def apply_caller_action(record: dict, action: Any) -> dict:
    """Copy scheduling fields from an MCP `caller_action`, keeping any the server omitted."""
    if isinstance(action, dict):
        for key in ("freshness", "fresh_until", "next_check_at", "next_check_reason"):
            if action.get(key) is not None:
                record[key] = action[key]
    return record


def build_record(card: dict, action: Any = None) -> dict:
    target = target_of(card)
    record = {
        "follow_id": card.get("follow_id"),
        "target_kind": target[0] if target else None,
        "target_id": target[1] if target else None,
        "follow_card": card,
        "fresh_until": card.get("fresh_until"),
        "next_trigger": card.get("next_trigger"),
        "pending_review": None,
    }
    return apply_caller_action(record, action)


class FollowStore:
    """One JSON file per follow, replaced atomically. The files are the index."""

    def __init__(self, root: Path):
        self.follows_dir = Path(root) / "follows"
        self.baselines_dir = Path(root) / "baselines"
        self._lock = threading.Lock()

    def save(self, record: dict) -> Path:
        path = self._follow_path(record.get("follow_id"))
        self._write(path, record)
        return path

    def get(self, follow_id: str) -> dict | None:
        path = self._follow_path(follow_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def delete(self, follow_id: str) -> bool:
        path = self._follow_path(follow_id)
        if not path.exists():
            return False
        path.unlink()
        return True

    def all(self) -> tuple[list[dict], list[str]]:
        """Return (records, unreadable file names). One bad file must not hide the others."""
        records: list[dict] = []
        unreadable: list[str] = []
        if not self.follows_dir.is_dir():
            return records, unreadable
        for path in sorted(self.follows_dir.glob("follow_*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(record.get("follow_card"), dict):
                    raise ValueError("record has no follow_card")
                records.append(record)
            except (OSError, ValueError, AttributeError):
                unreadable.append(path.name)
        records.sort(key=lambda r: (str(r.get("next_check_at") or ""), str(r.get("follow_id"))))
        return records, unreadable

    def find_target(self, kind: str, target_id: str) -> dict | None:
        records, _ = self.all()
        for record in records:
            if record.get("target_kind") == kind and record.get("target_id") == target_id:
                return record
        return None

    def save_baseline(self, thesis_id: str, pack_versions: list[dict]) -> None:
        self._write(
            self._baseline_path(thesis_id),
            {"thesis_id": thesis_id, "pack_versions": pack_versions},
        )

    def get_baseline(self, thesis_id: str) -> list[dict] | None:
        path = self._baseline_path(thesis_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("pack_versions")

    def _follow_path(self, follow_id: Any) -> Path:
        # The id becomes a file name, so it must match the server's own pattern.
        if not isinstance(follow_id, str) or not FOLLOW_ID_RE.match(follow_id):
            raise ValueError(f"Invalid follow id: {follow_id!r}")
        return self.follows_dir / f"{follow_id}.json"

    def _baseline_path(self, thesis_id: str) -> Path:
        digest = hashlib.sha256(thesis_id.encode("utf-8")).hexdigest()[:32]
        return self.baselines_dir / f"{digest}.json"

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
