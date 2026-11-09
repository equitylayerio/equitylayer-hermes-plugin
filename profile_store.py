"""The person's local research profile: which sectors they research, how often to check, which language.

It lets a returning person skip the setup questions. It lives next to the harnesses under Hermes's
plugin-data and is never sent to EquityLayer. Every field is validated against a fixed shape, so the
recall list can show it without quoting free text.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .harness_store import PLUGIN_NAME, today_taipei

# Mirrors ONBOARDING_SECTORS in EquityLayer's setup prompt (lib/harness.ts). Order and wording are AC's
# (2026-11-10). Update both, and the coverage table in the README, when a theme goes live.
SECTORS = (
    {"id": "optical_cpo", "label": "CPO and optical networking", "status": "live readings", "recommended": True,
     "gloss": "Co-packaged optics: the optics move next to the switch chip, so data leaves the chip as light."},
    {"id": "space_infrastructure", "label": "Space infrastructure",
     "status": "variables are being added; today you would mostly see gaps", "recommended": False,
     "gloss": "Launch cadence and satellite backlog turning into revenue for launch and satellite suppliers."},
    {"id": "custom_asic", "label": "Custom AI chips (ASIC)", "status": "live readings, tracking only, no Research Pack",
     "recommended": False,
     "gloss": "Chips designed for one hyperscaler's own AI workloads, built with design-service partners and foundries."},
    {"id": "other", "label": "Something else",
     "status": "for example Physical AI (variables listed, most readings withheld) or your own topic; "
               "the planner says what the catalog cannot cover",
     "recommended": False, "gloss": ""},
)
SECTOR_IDS = tuple(s["id"] for s in SECTORS) + ("physical_ai",)
SECTOR_LABELS = {s["id"]: s["label"] for s in SECTORS} | {"physical_ai": "Physical AI"}
CHECKS = ("daily", "weekly", "manual")

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TIMEZONE_RE = re.compile(r"^(UTC|[A-Z][A-Za-z_]+(/[A-Za-z0-9_+\-]+){1,2})$")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}$")
FIELDS = ("sectors", "has_view", "check", "check_time", "timezone", "language")


def default_profile_store() -> "ProfileStore":
    from plugins.plugin_storage import plugin_data_dir

    return ProfileStore(Path(plugin_data_dir(PLUGIN_NAME)))


def validate_fields(fields: dict) -> dict:
    """Return the cleaned subset of `fields`. Raises ValueError naming the first bad field."""
    clean: dict[str, Any] = {}
    if "sectors" in fields:
        sectors = fields["sectors"]
        if isinstance(sectors, str):
            sectors = [sectors]
        if not isinstance(sectors, list) or not 1 <= len(sectors) <= len(SECTOR_IDS):
            raise ValueError(f"sectors must be a list of 1 to {len(SECTOR_IDS)} of: {', '.join(SECTOR_IDS)}")
        seen: list[str] = []
        for sector in sectors:
            if sector not in SECTOR_IDS:
                raise ValueError(f"Unknown sector {sector!r}; use one of: {', '.join(SECTOR_IDS)}")
            if sector not in seen:
                seen.append(sector)
        clean["sectors"] = seen
    if "has_view" in fields:
        if not isinstance(fields["has_view"], bool):
            raise ValueError("has_view must be true or false")
        clean["has_view"] = fields["has_view"]
    if "check" in fields:
        if fields["check"] not in CHECKS:
            raise ValueError(f"check must be one of: {', '.join(CHECKS)}")
        clean["check"] = fields["check"]
    if "check_time" in fields:
        if not isinstance(fields["check_time"], str) or not TIME_RE.match(fields["check_time"]):
            raise ValueError("check_time must be HH:MM (24-hour)")
        clean["check_time"] = fields["check_time"]
    if "timezone" in fields:
        if not isinstance(fields["timezone"], str) or not TIMEZONE_RE.match(fields["timezone"]):
            raise ValueError("timezone must be an Area/City name such as Asia/Taipei, or UTC")
        clean["timezone"] = fields["timezone"]
    if "language" in fields:
        if not isinstance(fields["language"], str) or not LANGUAGE_RE.match(fields["language"]):
            raise ValueError("language must be a language tag such as en or zh-Hant")
        clean["language"] = fields["language"]
    return clean


class ProfileStore:
    def __init__(self, root: Path):
        self.path = Path(root) / "profile.json"
        self._lock = threading.Lock()

    def get(self) -> dict | None:
        """The saved profile, or None. A damaged file reads as None, so onboarding simply runs again."""
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        try:
            clean = validate_fields({k: data[k] for k in FIELDS if k in data})
        except ValueError:
            return None
        updated = data.get("updated_at")
        if isinstance(updated, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", updated):
            clean["updated_at"] = updated
        return clean

    def save(self, fields: dict, now: datetime | None = None) -> dict:
        """Merge validated fields into the saved profile."""
        profile = self.get() or {}
        profile.update(validate_fields(fields))
        profile["updated_at"] = today_taipei(now)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(profile, handle, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        return profile


def describe(profile: dict | None) -> str:
    """One line built only from validated fields and fixed labels."""
    if not profile:
        return ""
    parts = []
    if profile.get("sectors"):
        parts.append("researches " + ", ".join(SECTOR_LABELS[s] for s in profile["sectors"]))
    check = profile.get("check")
    if check == "manual":
        parts.append("checks only when asked")
    elif check in ("daily", "weekly"):
        when = "every day" if check == "daily" else "every Monday"
        at = f" at {profile['check_time']}" if profile.get("check_time") else ""
        tz = f" {profile['timezone']}" if profile.get("timezone") else ""
        parts.append(f"checks {when}{at}{tz}")
    if profile.get("language"):
        parts.append(f"language {profile['language']}")
    return "; ".join(parts)
