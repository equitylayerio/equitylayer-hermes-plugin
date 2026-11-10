"""What each tracked company does in its supply chain, in one plain sentence, from the company's own description.

The text ships with the plugin (data/company_roles.json) and is shown as data with its source. It says what a
company makes, never whether it is a good investment. Entries that fail the shape check are ignored.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROLES_FILE = Path(__file__).parent / "data" / "company_roles.json"
ENTITY_RE = re.compile(r"^[A-Z0-9]{1,6}\.[A-Z]{1,4}$")
MAX_ROLE = 200


def _clean(entry: Any) -> dict | None:
    if not isinstance(entry, dict):
        return None
    role, url, step = entry.get("role"), entry.get("source_url"), entry.get("step")
    if not (isinstance(role, str) and role.strip() and len(role) <= MAX_ROLE):
        return None
    # Some issuers' own sites only serve plain HTTP; keep the source, but only https is linked.
    if not (isinstance(url, str) and url.startswith(("https://", "http://")) and len(url) < 500):
        return None
    if not (isinstance(step, str) and 0 < len(step) <= 60):
        return None
    order = entry.get("step_order")
    return {
        "name": str(entry.get("name") or "")[:80],
        "role": " ".join(role.split()),
        "step": step.strip(),
        "step_order": order if isinstance(order, int) else 99,
        "source_title": str(entry.get("source_title") or "")[:160],
        "source_url": url,
    }


@lru_cache(maxsize=1)
def load(path: str = str(ROLES_FILE)) -> dict[str, dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    companies = data.get("companies") if isinstance(data, dict) else None
    out: dict[str, dict] = {}
    for entity, entry in (companies or {}).items():
        clean = _clean(entry)
        if clean and isinstance(entity, str) and ENTITY_RE.match(entity):
            out[entity] = clean
    return out


def role_for(entity: Any) -> dict | None:
    return load().get(entity) if isinstance(entity, str) else None
