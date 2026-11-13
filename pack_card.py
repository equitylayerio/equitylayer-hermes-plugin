"""The Research Pack card, shaped like EquityLayer's own card.

EquityLayer serves one card per Pack (get_research_pack with format "card", and the show_research_pack_card
MCP App). The website's /dashboard and this plugin's dashboard draw the same fields, so a person sees the same
card in every place. When the server's card is saved on the follow it is used as it is; otherwise the card is
built from the Pack summary and the readings this plugin already keeps. No field is written by a model.
"""

from __future__ import annotations

from typing import Any

# Same names as EquityLayer's onboarding sectors and the website card (lib/thesis-card.ts INDUSTRY_LABEL).
INDUSTRY = {
    "optical_cpo": ("CPO and optical networking", "CPO 與光通訊"),
    "custom_asic": ("Custom AI chips (ASIC)", "客製化 AI 晶片（ASIC）"),
    "space_infrastructure": ("Space infrastructure", "太空基礎設施"),
    "physical_ai": ("Physical AI", "Physical AI"),
    "ai_compute": ("AI compute", "AI 運算"),
}
MCP_URL = "https://equitylayer.io/mcp"
FRONT_VARIABLES = 3


def industry(theme_id: Any) -> list[str]:
    pair = INDUSTRY.get(str(theme_id or ""))
    return list(pair) if pair else [str(theme_id or "Research"), str(theme_id or "Research")]


def is_server_card(value: Any) -> bool:
    return isinstance(value, dict) and value.get("kind") == "research_pack_card" and isinstance(value.get("pack_id"), str)


def build(summary: dict, rows: dict[str, dict] | None = None, next_check: Any = None,
          server_card: Any = None) -> dict:
    """A card for one followed Pack. `rows` are the plugin's latest readings by variable id."""
    if is_server_card(server_card):
        card = {k: v for k, v in server_card.items() if k != "kind"}
        if next_check:  # the follow's own next check wins over the edition date
            card["check"] = {**(card.get("check") or {}), "next_check": next_check}
        return card
    rows = rows or {}
    pack_id = summary.get("pack_id")
    watch = []
    for vid in summary.get("variables") or []:
        row = rows.get(vid) or {}
        latest = row.get("latest") if isinstance(row.get("latest"), dict) else None
        has_value = latest is not None and latest.get("value") is not None and not latest.get("withheld")
        watch.append({
            "id": vid,
            "name": [row.get("name") or vid, row.get("name") or vid],
            "latest": {"period": latest.get("period"), "value": latest.get("value"), "unit": row.get("unit")} if has_value else None,
            "change": row.get("change") if has_value else None,
            "next_reading": row.get("next_reading"),
        })
    hyps = [h for h in summary.get("hypotheses") or [] if isinstance(h, dict)]
    # Core hypotheses first, as the Pack orders its reads.
    hyps.sort(key=lambda h: {"core": 0, "supporting": 1, "risk": 2}.get(h.get("role") or "core", 0))
    version = summary.get("revision")
    return {
        "card": f"{pack_id}@{version}" if version else pack_id,
        "pack_id": pack_id,
        "version": version,
        "industry": industry(summary.get("theme_id")),
        "category": summary.get("category"),
        "title": summary.get("title") or pack_id,
        "view": summary.get("view"),
        "mcp": MCP_URL,
        "follow": {"tool": "create_research_follow", "arguments": {"pack_id": pack_id}},
        "check": {"tool": "check_research_follow", "next_check": next_check},
        "watch": watch,
        "wrong_if": [h["falsifier"] for h in hyps if h.get("falsifier")],
        "cite": summary.get("url"),
    }


def front_variables(card: dict) -> list[dict]:
    watch = card.get("watch") if isinstance(card.get("watch"), list) else []
    with_value = [w for w in watch if isinstance(w, dict) and w.get("latest")]
    blank = [w for w in watch if isinstance(w, dict) and not w.get("latest")]
    return (with_value + blank)[:FRONT_VARIABLES]
