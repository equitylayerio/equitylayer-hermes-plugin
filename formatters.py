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


def _plain(text: Any) -> str:
    return str(text or "").replace("https://", "").replace("http://", "")


def _domain(url: Any) -> str:
    host = _plain(url).split("/")[0]
    return host[4:] if host.startswith("www.") else host


def _clip(text: Any, limit: int = 320) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def pack_summary(pack: Any) -> dict | None:
    """What a followed Pack holds, kept on the follow: its view, hypotheses, what would prove each wrong, and
    the readings it watches. Text is clipped; ids that are not variable ids are dropped."""
    from .watch_store import VARIABLE_RE

    if not isinstance(pack, dict):
        return None
    cite = pack.get("cite_as") if isinstance(pack.get("cite_as"), dict) else {}
    hyps, variables = [], []
    for h in pack.get("hypotheses") or []:
        if not isinstance(h, dict):
            continue
        a = h.get("assertion") if isinstance(h.get("assertion"), dict) else {}
        test = h.get("test") if isinstance(h.get("test"), dict) else {}
        watched = [w["variable"] for w in h.get("watches") or []
                   if isinstance(w, dict) and isinstance(w.get("variable"), str) and VARIABLE_RE.match(w["variable"])]
        variables += [v for v in watched if v not in variables]
        statement = a.get("statement") or h.get("statement") or h.get("title")
        if statement:
            hyps.append({"statement": _clip(statement, 400), "confidence": h.get("confidence"), "state": h.get("state"),
                         "falsifier": _clip(test.get("falsifier")) if test.get("falsifier") else None,
                         "due": test.get("due"), "variables": watched})
    url = cite.get("url") if str(cite.get("url") or "").startswith("https://") else None
    return {"pack_id": pack.get("pack_id"), "title": _clip(cite.get("title") or pack.get("title") or pack.get("pack_id"), 200),
            "view": _clip(pack.get("view"), 400) if pack.get("view") else None, "theme_id": pack.get("theme_id"),
            "revision": pack.get("revision") or pack.get("pack_version"), "as_of": pack.get("as_of"), "url": url,
            "hypotheses": hyps[:6], "variables": variables[:8]}


def format_pack_thesis(summary: dict) -> str:
    """The followed Pack's thesis, in plain lines: what it holds and what would prove each part wrong."""
    lines = []
    for n, h in enumerate(summary.get("hypotheses") or [], 1):
        line = f"{n}. {h.get('statement')} (confidence {h.get('confidence') or '—'})"
        if h.get("falsifier"):
            line += f"\n   - Would be wrong if: {h['falsifier']}" + (f" (by {h['due']})" if h.get("due") else "")
        lines.append(line)
    return _join(f"## EquityLayer thesis: {summary.get('title')}",
                 f"**View:** {summary['view']}" if summary.get("view") else "",
                 "\n".join(lines))


def _format_pack_v1(pack: dict) -> str:
    """Research Pack format v1: a view, hypotheses with their tests and watches, evidence claims, sources."""
    cite = pack.get("cite_as") if isinstance(pack.get("cite_as"), dict) else {}
    fresh = pack.get("freshness") if isinstance(pack.get("freshness"), dict) else {}
    meta = [f"revision {pack.get('revision')}" if pack.get("revision") else None,
            f"as of {pack.get('as_of')}" if pack.get("as_of") else None,
            f"status {pack.get('status')}" if pack.get("status") else None,
            f"fresh until {fresh.get('fresh_until')}" if fresh.get("fresh_until") else None]
    hyps = []
    for n, h in enumerate([h for h in pack.get("hypotheses") or [] if isinstance(h, dict)], 1):
        a = h.get("assertion") if isinstance(h.get("assertion"), dict) else {}
        test = h.get("test") if isinstance(h.get("test"), dict) else {}
        watches = ", ".join(f"`{w.get('variable')}`" for w in h.get("watches") or [] if isinstance(w, dict) and w.get("variable"))
        lines = [f"{n}. **{_clip(a.get('statement'), 400)}**",
                 f"   - Confidence {h.get('confidence') or '—'} · state {h.get('state') or '—'}"]
        if test.get("falsifier"):
            lines.append(f"   - Would be wrong if: {_clip(test['falsifier'])}" + (f" (by {test['due']})" if test.get("due") else ""))
        if watches:
            lines.append(f"   - Watching: {watches}")
        if a.get("limitation"):
            lines.append(f"   - Limits: {_clip(a['limitation'])}")
        hyps.append("\n".join(lines))
    label = {"reported_fact": "reported fact", "management_claim": "management claim", "derived_value": "derived value"}
    claims, all_claims = [], [c for c in pack.get("claims") or [] if isinstance(c, dict)]
    for c in all_claims[:8]:
        a = c.get("assertion") if isinstance(c.get("assertion"), dict) else {}
        prov = c.get("provenance") if isinstance(c.get("provenance"), dict) else {}
        ids = ", ".join(str(i) for i in prov.get("source_ids") or [] if isinstance(i, (str, int)))
        claims.append(f"- ({label.get(a.get('kind'), a.get('kind') or 'claim')}) {_clip(a.get('statement'), 260)}"
                      + (f" [{ids}]" if ids else ""))
    if len(all_claims) > 8:
        claims.append(f"- …and {len(all_claims) - 8} more on the Pack page.")
    all_sources = [s for s in pack.get("sources") or [] if isinstance(s, dict)]
    sources = [f"- {s.get('id')}: {s.get('publisher') or ''}" + (f" ({_domain(s.get('url'))})" if _domain(s.get("url")) else "")
               for s in all_sources[:12]]
    if len(all_sources) > 12:
        sources.append(f"- …and {len(all_sources) - 12} more on the Pack page.")
    return _join(
        f"## {cite.get('title') or pack.get('title') or pack.get('pack_id')}",
        " · ".join(m for m in meta if m),
        f"**View:** {pack['view']}" if pack.get("view") else "",
        _section("Hypotheses", "\n".join(hyps)) if hyps else "",
        _section("Evidence", "\n".join(claims)) if claims else "",
        _section("Not covered", _bullets(pack.get("not_covered"))),
        _section("Sources", "\n".join(sources)) if sources else "",
        f"Cite as: {_plain(cite.get('text'))}" if cite.get("text") else "",
        DISCLAIMER,
    )


def format_pack(pack: dict, max_records: int = 10, title: Any = None) -> str:
    if pack.get("view") or any(isinstance(h, dict) and isinstance(h.get("assertion"), dict)
                               for h in pack.get("hypotheses") or []):
        return _format_pack_v1(pack)
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
    summary = record.get("pack") if isinstance(record.get("pack"), dict) else None
    if summary:
        readings = record.get("readings_id")
        return _join(
            f"**{verb} EquityLayer's Research Pack:** {summary.get('title')}",
            f"Its hypotheses{' and the readings it watches' if readings else ''} are saved on this machine as one "
            f"item, `{record.get('follow_id')}`. Next check: {record.get('next_check_at') or 'unknown'}.",
            schedule_hint,
        )
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
    if result.get("title") and result.get("status") == "current":
        # The server's wording ("Keep this Follow Card") is for agents; say what it means.
        return _join(f"**EquityLayer Research Pack · {result['title']}:** current. None of the readings it "
                     "watches has moved since the last check.",
                     f"Next check: {result['next_check_at']}" if result.get("next_check_at") else "")
    lines = [
        f"**`{follow_id}`** ({result.get('title') or result.get('target_id')}): {result.get('status')}",
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
