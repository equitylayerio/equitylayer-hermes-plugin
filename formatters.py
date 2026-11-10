"""Render EquityLayer payloads as chat-readable markdown. Values are shown as published."""

from __future__ import annotations

from typing import Any, Iterable

DISCLAIMER = "_Research evidence, not a trade order. Not investment advice._"
MAX_CHANGES_SHOWN = 12


def _cell(value: Any) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _table(headers: list[str], rows: Iterable[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return "\n".join(lines)


def _bullets(items: Any) -> str:
    return "\n".join(f"- {item}" for item in items or [])


def _thousands(value: Any) -> Any:
    return f"{value:,}" if isinstance(value, (int, float)) and not isinstance(value, bool) else value


def _pct(value: Any) -> Any:
    return f"{value:+.2f}%" if isinstance(value, (int, float)) and not isinstance(value, bool) else value


def _join(*blocks: Any) -> str:
    return "\n\n".join(block for block in blocks if block)


def format_registry(
    entries: list[dict], registry_url: Any = None, *, note: Any = None, industries: Any = None
) -> str:
    source = f"Source: EquityLayer Research Registry — {registry_url}" if registry_url else ""
    if not entries:
        covered = ", ".join(map(str, industries)) if isinstance(industries, list) and industries else ""
        return _join(
            "## EquityLayer Research Registry",
            "**No Research Pack is published right now.** The registry lists released or in-review entries only, "
            "and none is current. Older monthly-revenue packs are retired and are not shown as current.",
            f"Industries in research: {covered}." if covered else "",
            str(note) if note else "",
            "You can still track **your own thesis** against EquityLayer's variable catalog: "
            "`/equitylayer:start`.",
            source,
        )
    def status(entry: dict) -> str:
        return "in review, not published yet" if entry.get("status") == "in_review" or entry.get("kind") == "in_review" \
            else str(entry.get("status") or "published")

    rows = [
        [
            entry.get("id"),
            entry.get("title"),
            status(entry),
            "locked" if entry.get("locked") else entry.get("access"),
            entry.get("fresh_until"),
            entry.get("next_check_at"),
        ]
        for entry in entries
    ]
    table = _table(["id", "title", "status", "access", "fresh until", "next check"], rows)
    in_review = any(status(e).startswith("in review") for e in entries)
    published = any(not status(e).startswith("in review") for e in entries)
    return _join(
        "## EquityLayer Research Registry",
        table,
        "Entries in review are not published yet: they can't be read or followed." if in_review else "",
        "Next: ask to read or follow a published one by its id." if published else "",
        source,
    )


def format_pack(pack: dict, max_records: int = 10, title: Any = None) -> str:
    pack_id = pack.get("pack_id") or "research pack"
    meta = [
        f"Period **{pack['report_period'] or pack.get('period')}**" if pack.get("report_period") else None,
        f"version `{pack['pack_version']}`" if pack.get("pack_version") else None,
        f"fresh until {pack['fresh_until']}" if pack.get("fresh_until") else None,
    ]
    return _join(
        f"## {title or pack_id}" + (f" (`{pack_id}`)" if title else ""),
        " · ".join(m for m in meta if m),
        _health_note(pack.get("health")),
        f"**What changed:** {pack['what_changed']}" if pack.get("what_changed") else "",
        _readthrough(pack.get("research_readthrough")),
        _hypotheses(pack.get("hypotheses")),
        _records(pack.get("records"), max_records),
        _unavailable(pack.get("unavailable_symbols")),
        _claims(pack.get("public_claims")),
        _section("Not covered", _bullets(pack.get("not_covered"))),
        _section("Unknowns", _bullets(pack.get("unknowns"))),
        f"**Falsifier:** {pack['falsifier']}" if pack.get("falsifier") else "",
        f"**Next trigger:** {pack['next_trigger']}" if pack.get("next_trigger") else "",
        _methodology(pack.get("methodology")),
        _source(pack.get("source")),
        f"Snapshot SHA-256: `{pack['snapshot_hash']}`" if pack.get("snapshot_hash") else "",
        DISCLAIMER,
    )


def _section(heading: str, body: str) -> str:
    return f"### {heading}\n\n{body}" if body else ""


def _health_note(health: Any) -> str:
    if not isinstance(health, dict):
        return ""
    note = f"Pack health: {health.get('state', 'unknown')}"
    if health.get("latest_release_verified") is False:
        note += " · the latest official release is not yet verified"
    return note


def _readthrough(data: Any) -> str:
    if not isinstance(data, dict) or not data.get("summary"):
        return ""
    label = "not human-reviewed" if data.get("review_status") == "not_human_reviewed" else data.get("review_status")
    return f"**Read-through{f' ({label})' if label else ''}:** {data['summary']}"


def _hypotheses(items: Any) -> str:
    if not isinstance(items, list) or not items:
        return ""
    rows = [
        [h.get("id"), h.get("statement") or h.get("title"), h.get("confidence"), h.get("last_check")]
        for h in items
        if isinstance(h, dict)
    ]
    return _section("Publisher hypotheses", _table(["id", "hypothesis", "confidence", "last check"], rows))


def _records(records: Any, max_records: int) -> str:
    if not isinstance(records, list) or not records:
        return ""
    shown = [r for r in records[:max_records] if isinstance(r, dict)]
    if shown and "revenue_thousand_twd" in shown[0]:
        table = _table(
            ["symbol", "company", "revenue (NT$ thousand)", "MoM", "YoY", "issuer note"],
            [
                [
                    r.get("symbol"),
                    r.get("company_name"),
                    _thousands(r.get("revenue_thousand_twd")),
                    _pct(r.get("mom_pct")),
                    _pct(r.get("yoy_pct")),
                    r.get("issuer_note"),
                ]
                for r in shown
            ],
        )
    else:
        # Unknown pack shape: show its scalar fields rather than guess at meaning.
        keys = [k for k, v in shown[0].items() if isinstance(v, (str, int, float))][:6] if shown else []
        table = _table(keys, [[r.get(k) for k in keys] for r in shown]) if keys else ""
    more = f"Showing {len(shown)} of {len(records)} records." if len(records) > len(shown) else ""
    return _section("Records", _join(table, more))


def _unavailable(symbols: Any) -> str:
    return f"**Unavailable symbols:** {', '.join(map(str, symbols))}" if symbols else ""


def _claims(claims: Any) -> str:
    if not isinstance(claims, list) or not claims:
        return ""
    rows = [[c.get("id"), c.get("status"), c.get("due"), c.get("revisit")] for c in claims if isinstance(c, dict)]
    return _section("Public claims", _table(["id", "status", "due", "resolution"], rows))


def _methodology(methodology: Any) -> str:
    if isinstance(methodology, dict):
        text = methodology.get("calculations") or methodology.get("summary")
        return f"**Methodology:** {text}" if text else ""
    return f"**Methodology:** {methodology}" if methodology else ""


def _source(source: Any) -> str:
    if not isinstance(source, dict):
        return f"### Source\n\n{source}" if source else ""
    lines = [
        ("Provider", source.get("provider")),
        ("Dataset", source.get("dataset")),
        ("Published", source.get("published_on")),
        ("Primary data", source.get("api_url") or source.get("url")),
        ("License", source.get("license")),
        ("Attribution", source.get("attribution")),
    ]
    return _section("Source", _bullets(f"{k}: {v}" for k, v in lines if v))


def format_scorecard(data: dict) -> str:
    card = data.get("scorecard") if isinstance(data.get("scorecard"), dict) else {}
    resolution = card.get("resolution") or {}
    timeliness = card.get("timeliness") or {}
    evidence = card.get("evidence") or {}
    corrections = card.get("corrections") or {}
    reproducibility = card.get("reproducibility") or {}
    cite = data.get("cite_as") or {}
    rows = [
        ["Claims", f"{resolution.get('total', 0)} total: {resolution.get('Confirmed', 0)} confirmed, "
                   f"{resolution.get('Missed', 0)} missed, {resolution.get('Mixed', 0)} mixed, "
                   f"{resolution.get('Open', 0)} open"],
        ["Freshness", f"{timeliness.get('freshness', 'unknown')}, {timeliness.get('days_overdue', 0)} days overdue"],
        ["Resolved within SLA", f"{timeliness.get('resolved_within_sla', 0)} of {timeliness.get('resolved_total', 0)}"],
        ["Sources", f"{evidence.get('sources', 0)} total, {evidence.get('official', 0)} official, "
                    f"{evidence.get('rederivable', 0)} re-derivable"],
        ["Amended before resolution", corrections.get("amended_before_resolution", 0)],
        ["Immutable editions", f"{reproducibility.get('immutable_editions', 0)}"
                               f" ({'all hashed' if reproducibility.get('all_hashed') else 'not all hashed'})"],
    ]
    return _join(
        f"## Scorecard: {data.get('title') or data.get('id')}",
        f"`{data.get('id')}` · edition {data.get('edition')} · fresh until {data.get('fresh_until')}",
        _table(["measure", "result"], rows),
        f"Cite as: {cite['text']}" if isinstance(cite, dict) and cite.get("text") else "",
        "_Measures research quality, not popularity. Not a recommendation or investment advice._",
    )


def format_follow_created(record: dict, schedule_hint: str, already_following: bool = False) -> str:
    verb = "Already following" if already_following else "Now following"
    return _join(
        f"**{verb}** `{record.get('target_id')}` ({record.get('target_kind')}).",
        f"Follow id: `{record.get('follow_id')}` · next check: {record.get('next_check_at') or 'unknown'}"
        + (f" ({record['next_check_reason']})" if record.get("next_check_reason") else ""),
        "The card is stored only on this machine. EquityLayer does not store it.",
        schedule_hint,
    )


def format_follow_list(rows: list[dict], unreadable: list[str], schedule_hint: str) -> str:
    if not rows and not unreadable:
        return "No followed Research Pack yet. Ask whether one is published for your sector."
    table = _table(
        ["follow id", "target", "kind", "fresh until", "next check", "state"],
        [
            [r.get("follow_id"), r.get("target_id"), r.get("target_kind"), r.get("fresh_until"),
             r.get("next_check_at"), r.get("state")]
            for r in rows
        ],
    )
    bad = f"Unreadable local files: {', '.join(unreadable)}" if unreadable else ""
    return _join("## Local EquityLayer follows", table, bad, schedule_hint)


def format_check(result: dict) -> str:
    follow_id = result.get("follow_id") or "supplied card"
    if result.get("status") == "error":
        return f"**`{follow_id}`:** check failed: {result.get('error')}. {result.get('message') or ''}".strip()
    review = result.get("needs_review")
    lines = [
        f"**`{follow_id}`** (`{result.get('target_id')}`): {result.get('status')}",
        result.get("message") or "",
        f"Next check: {result['next_check_at']}" if result.get("next_check_at") and not review else "",
        _changes_table(result.get("variable_changes")),
        _events(result.get("new_events")),
    ]
    if review:
        lines.append(
            f"Review the change, then run `/el seen {follow_id}` to move this follow to the new "
            "baseline. The stored card stays unchanged until then."
        )
    return _join(*lines)


def _changes_table(changes: Any) -> str:
    if not isinstance(changes, list) or not changes:
        return ""
    shown = [c for c in changes[:MAX_CHANGES_SHOWN] if isinstance(c, dict)]
    table = _table(
        ["variable", "kind", "period", "value", "unit", "change", "source"],
        [
            [c.get("name") or c.get("variable"), c.get("change_kind"), c.get("period"), _thousands(c.get("value")),
             c.get("unit"), _pct(c.get("change_pct")), c.get("source_url")]
            for c in shown
        ],
    )
    more = f"Showing {len(shown)} of {len(changes)} changes." if len(changes) > len(shown) else ""
    return _join(table, more)


def _events(events: Any) -> str:
    if not isinstance(events, list) or not events:
        return ""
    return _section("New events", _bullets(
        f"{e.get('at')}: {e.get('title')}" for e in events if isinstance(e, dict)
    ))


def format_check_run(results: list[dict], awaiting: list[dict], due_mode: bool) -> str:
    blocks = [format_check(r) for r in results]
    if awaiting:
        blocks.append(
            "Still awaiting your review: " + ", ".join(f"`{r.get('follow_id')}`" for r in awaiting)
        )
    if not blocks:
        return "No local follows are due." if due_mode else "Nothing to check."
    return _join(*blocks, DISCLAIMER)
