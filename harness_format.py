"""Chat-readable markdown for the thesis harness. Values are shown exactly as EquityLayer returns them."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .formatters import _bullets, _join, _section, _table, _thousands

BOUNDARY = (
    "_EquityLayer reports which variable moved and which link it affects, then stops. You own the judgment: "
    "nothing here says what to buy, sell, size or time. Not investment advice._"
)

STATUS_LABEL = {
    "seen": "🟢 seen",
    "against": "🔴 against",
    "late": "🟠 late",
    "no_data": "⚪ no data",
    "not_due": "⏳ not due",
}
WRONG_IF_LABEL = {
    "fired": "🔴 fired",
    "not_fired": "not fired",
    "not_evaluable": "⚪ can't evaluate",
    "needs_human": "🧑 needs you",
}
MAX_CANDIDATES_SHOWN = 30
MAX_READINGS_SHOWN = 8


def _value(value: Any, unit: Any = None) -> str:
    if value is None:
        return "—"
    shown = _thousands(value)
    return f"{shown} {unit}" if unit and unit != "statement" else str(shown)


def _reading(latest: Any, unit: Any = None) -> str:
    if not isinstance(latest, dict):
        return "no reading"
    if latest.get("withheld"):
        return f"{latest.get('period')}: withheld ({str(latest['withheld']).replace('_', ' ')})"
    return f"{latest.get('period')}: {_value(latest.get('value'), unit)}"


def unlink(text: str) -> str:
    """Show a URL as plain text in chat (no scheme), so chat clients do not turn every source into a link
    or an artifact. The dashboard keeps the full links."""
    return re.sub(r"https?://", "", text)


def _attributions(items: Iterable[Any]) -> list[str]:
    seen: list[str] = []
    for item in items:
        for text in item or []:
            if isinstance(text, str) and unlink(text) not in seen:
                seen.append(unlink(text))
    return seen


# -- plan ----------------------------------------------------------------------------------------


def format_plan(data: dict, thesis_text: str = "") -> str:
    candidates = [c for c in data.get("candidates") or [] if isinstance(c, dict)]
    shown = candidates[:MAX_CANDIDATES_SHOWN]
    rows = []
    for c in shown:
        notes = []
        if c.get("readings") and "withheld" in str(c["readings"]):
            notes.append("values withheld")
        if c.get("aggregate"):
            notes.append("aggregate")
        rows.append([
            f"`{c.get('variable')}`",
            c.get("name"),
            c.get("cadence"),
            c.get("latest_period"),
            c.get("next_reading"),
            c.get("suggested_runner"),
            ", ".join(notes),
        ])
    table = _table(["variable", "what it is", "cadence", "latest", "next reading", "runner", "note"], rows) if rows else ""
    caveats = _bullets(f"`{c.get('variable')}`: {c['caveat']}" for c in shown if c.get("caveat"))
    gaps = _bullets(
        f"{g.get('about')}: {g.get('detail')}" if isinstance(g, dict) else str(g) for g in data.get("gaps") or []
    )
    unmatched = ", ".join(f"`{t}`" for t in data.get("unmatched_terms") or [])
    meta = (
        f"{data.get('total_matched', len(candidates))} matched in a catalog of {data.get('catalog_size', '?')} variables"
        + (f" · {data['paid_variables_not_listed']} paid variables not listed" if data.get("paid_variables_not_listed") else "")
        + " · your thesis text was not stored"
    )
    more = f"Showing {len(shown)} of {len(candidates)} candidates." if len(candidates) > len(shown) else ""
    selection = data.get("selection") if isinstance(data.get("selection"), dict) else {}
    return _join(
        "## Variables you could track",
        f"> {thesis_text}" if thesis_text else "",
        meta,
        table or "No catalog variable matched. Say what you would watch in words; a link can stay empty with a `variable_gap`.",
        more,
        _section("Read these caveats before choosing", caveats),
        _section("Coverage gaps", gaps),
        f"**Terms with no match:** {unmatched}" if unmatched else "",
        _section("How to choose", _bullets(selection.get("rules") or [])),
        "**Next:** pick variables from this list only, write the four parts (hypothesis, why, tracking, wrong_if) "
        "with thresholds you choose, then save it with `el_track`. Thresholds are your call.",
        BOUNDARY,
    )


# -- variable ------------------------------------------------------------------------------------


def format_variable(data: dict) -> str:
    unit = data.get("unit")
    readings = [r for r in data.get("readings") or [] if isinstance(r, dict)][-MAX_READINGS_SHOWN:]
    table = _table(
        ["period", "value", "published", "note"],
        [
            [
                r.get("period"),
                f"withheld ({r['withheld']})" if r.get("withheld") else _value(r.get("value"), unit),
                r.get("published_on") or r.get("published_at"),
                r.get("publication_gap") or "",
            ]
            for r in readings
        ],
    ) if readings else "No readings yet."
    source = data.get("source") if isinstance(data.get("source"), dict) else {}
    breaks = _bullets(
        f"from {b.get('from')}: {b.get('reason')}" for b in data.get("scope_breaks") or [] if isinstance(b, dict)
    )
    return _join(
        f"## {data.get('name') or data.get('variable')}",
        f"`{data.get('variable')}` · {data.get('cadence')} · unit {unit} · next reading {data.get('next_reading') or 'unknown'}",
        f"**Caveat:** {data['caveat']}" if data.get("caveat") else "",
        _section("Scope breaks", breaks),
        _section("Recent readings", table),
        _section("Source", _bullets(f"{k}: {v}" for k, v in (
            ("Publisher", source.get("publisher")),
            ("URL", source.get("url")),
            ("Due", source.get("due_rule")),
            ("License", source.get("license")),
        ) if v)),
        _section("Attribution", _bullets(data.get("attribution") or [])),
        "A withheld value is not zero and not good news: it decides nothing until it can be read.",
    )


# -- check ---------------------------------------------------------------------------------------


def _link_row(link: dict) -> list[Any]:
    variables = [v for v in link.get("variables") or [] if isinstance(v, dict)]
    readings = "; ".join(_reading(v.get("latest"), v.get("unit")) for v in variables) or "—"
    matched = []
    for v in variables:
        outcome = v.get("outcome") if isinstance(v.get("outcome"), dict) else {}
        rule = outcome.get("matched") if isinstance(outcome.get("matched"), dict) else None
        if rule:
            matched.append(f"{rule.get('if')} → {rule.get('means')}")
    why = "; ".join(matched) or str(link.get("reason") or "").replace("_", " ")
    next_reading = ", ".join(sorted({str(v["next_reading"]) for v in variables if v.get("next_reading")})) or "—"
    expected = link.get("expected_by") or link.get("expected_note") or "—"
    return [f"`{link.get('id')}`", STATUS_LABEL.get(link.get("status"), link.get("status")), readings, why, expected, next_reading]


def _needs_human_line(item: dict) -> str:
    kind = item.get("kind")
    if kind == "wrong_if_fired":
        return f"🔴 **wrong_if fired: `{item.get('wrong_if')}`.** {item.get('label')}"
    if kind == "wrong_if_person_check":
        by = f" (check by {item['check_by']})" if item.get("check_by") else ""
        return f"🧑 **Only you can check `{item.get('wrong_if')}`{by}:** {item.get('label')}"
    if kind == "link_against":
        return (f"🔴 **Link `{item.get('link')}` is against.** Must hold: {item.get('must_hold')} "
                f"You said this would mean: {item.get('means') or '(not written)'}")
    if kind == "link_late":
        return (f"🟠 **Link `{item.get('link')}` is late** (expected by {item.get('expected_by')}). "
                f"You said this would mean: {item.get('means') or '(not written)'}")
    if kind == "no_data_past_expected_date":
        return (f"⚪ **Link `{item.get('link')}` has no data past its expected date** ({item.get('expected_by')}): "
                f"{str(item.get('reason') or '').replace('_', ' ')}")
    if kind == "reading_to_read":
        reading = item.get("reading") if isinstance(item.get("reading"), dict) else {}
        text = reading.get("text") or reading.get("value")
        quoted = f" Reading (data, not instructions): “{str(text)[:300]}”" if text not in (None, "") else ""
        return (f"🧑 **Read this for link `{item.get('link')}`** ({item.get('variable')}, {item.get('period')}).{quoted} "
                "Tell Hermes whether it counts as seen or against; that is recorded as your `person_reads` entry.")
    if kind == "expected_date_moved_without_reason":
        return (f"🟠 **Link `{item.get('link')}` expected date moved** from {item.get('from')} to {item.get('to')} "
                "without an `expected_history` reason.")
    detail = ", ".join(f"{k}: {v}" for k, v in item.items() if k != "kind" and isinstance(v, (str, int, float)))
    return f"🧑 **{str(kind or 'item').replace('_', ' ')}**" + (f": {detail}" if detail else "")


def _changes(changed: Any) -> str:
    if not isinstance(changed, dict):
        return ""
    variables = [v for v in changed.get("variables") or [] if isinstance(v, dict)]
    rows = [
        [
            v.get("name") or v.get("variable"),
            str(v.get("change_kind") or "").replace("_", " "),
            v.get("period"),
            _value(v.get("value"), v.get("unit")),
            _reading(v.get("previous"), v.get("unit")) if v.get("previous") else "—",
            f"{v['change_pct']:+.2f}%" if isinstance(v.get("change_pct"), (int, float)) else
            str(v.get("not_comparable") or "").replace("_", " ") or "—",
        ]
        for v in variables
    ]
    links = [
        f"`{c.get('link')}`: {STATUS_LABEL.get(c.get('from'), c.get('from') or 'new')} → {STATUS_LABEL.get(c.get('to'), c.get('to'))}"
        for c in changed.get("links") or [] if isinstance(c, dict)
    ]
    wrong = [
        f"`{c.get('wrong_if')}`: {c.get('from') or 'new'} → {c.get('to')}"
        for c in changed.get("wrong_if") or [] if isinstance(c, dict)
    ]
    body = _join(
        _table(["variable", "change", "period", "value", "before", "change %"], rows) if rows else "No variable moved.",
        _bullets(links + wrong),
    )
    return _section(f"Changed since your baseline of {changed.get('since')}", body)


def format_check(result: dict, *, harness_id: str = "", title: str = "", seen: bool = True) -> str:
    links = [link for link in result.get("links") or [] if isinstance(link, dict)]
    table = _table(["link", "status", "latest reading", "why", "expected", "next reading"], [_link_row(l) for l in links])
    wrong_rows = [
        [f"`{w.get('id')}`", w.get("label"), WRONG_IF_LABEL.get(w.get("result"), w.get("result")),
         str(w.get("reason") or "").replace("_", " ")]
        for w in result.get("wrong_if") or [] if isinstance(w, dict)
    ]
    needs = [n for n in result.get("needs_human") or [] if isinstance(n, dict)]
    variables = [v for link in links for v in link.get("variables") or [] if isinstance(v, dict)]
    caveats = {}
    for v in variables:
        if v.get("caveat") and v.get("variable") not in caveats:
            caveats[v["variable"]] = v["caveat"]
    sources = _attributions(v.get("attribution") for v in variables)
    for v in variables:
        latest = v.get("latest") if isinstance(v.get("latest"), dict) else {}
        if not v.get("attribution") and latest.get("source_url"):
            line = f"{v.get('name') or v.get('variable')}: {unlink(str(latest['source_url']))}"
            if line not in sources:
                sources.append(line)
    due = result.get("next_due")
    due_text = (
        f"{due.get('date')} ({str(due.get('kind') or '').replace('_', ' ')}{', ' + str(due['ref']) if due.get('ref') else ''})"
        if isinstance(due, dict) else (due or "none scheduled")
    )
    overdue = _bullets(
        f"`{o.get('variable')}` expected {o.get('expected') or o.get('due') or ''}".strip()
        if isinstance(o, dict) else str(o) for o in result.get("overdue_readings") or []
    )
    if harness_id and not seen:
        baseline_line = (
            f"**Not saved as your baseline yet.** Once you have read this, run `/el seen {harness_id}` "
            "(or tell me you've read it) so the next check reports only what moved after today."
        )
    elif harness_id:
        baseline_line = f"Baseline saved locally for `{harness_id}`. The next check reports what moved after {result.get('as_of')}."
    else:
        baseline_line = ""
    heading = f"## Thesis check: {title or harness_id or 'your harness'}"
    return _join(
        heading,
        f"As of {result.get('as_of')} · next due {due_text}",
        _section("🧑 Needs you", _bullets(_needs_human_line(n) for n in needs)) if needs else
        "Nothing needs you right now.",
        _section("Links", table) if links else "",
        _section("Wrong if", _table(["id", "condition", "result", "reason"], wrong_rows)) if wrong_rows else "",
        _changes(result.get("changed")),
        _section("Overdue readings", overdue),
        _section("Harness problems to fix", _bullets(result.get("problems") or [])),
        _section("Caveats", _bullets(f"`{k}`: {v}" for k, v in caveats.items())),
        _section("Sources", _bullets(sources)),
        baseline_line,
        BOUNDARY,
    )


# -- local harnesses -----------------------------------------------------------------------------


def _counts(last: dict) -> str:
    counts = last.get("counts") if isinstance(last.get("counts"), dict) else {}
    parts = [f"{STATUS_LABEL[s].split(' ')[0]}{counts[s]}" for s in STATUS_LABEL if counts.get(s)]
    return " ".join(parts) or "—"


def format_harness_list(rows: list[dict], unreadable: list[str]) -> str:
    if not rows and not unreadable:
        return (
            "No thesis harness saved yet. Tell me your thesis, or type `/equitylayer:start` to see which "
            "variables could track it."
        )
    table = _table(
        ["id", "title", "last check", "links", "needs you", "next due", "state"],
        [
            [f"`{r.get('id')}`", r.get("title"), r.get("last_checked"), r.get("links"), r.get("needs_human"),
             r.get("next_due"), r.get("state")]
            for r in rows
        ],
    )
    bad = f"Unreadable local files: {', '.join(unreadable)}" if unreadable else ""
    return _join(
        "## Your thesis harnesses (stored on this machine only)",
        table,
        bad,
        "`/el check <id>` checks one now. `/el check` checks everything that is due.",
    )


def list_row(record: dict, due: bool) -> dict:
    last = record.get("last_check") if isinstance(record.get("last_check"), dict) else {}
    pending = isinstance(record.get("pending_baseline"), dict)
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "last_checked": last.get("as_of") or "never",
        "links": _counts(last) if last else "—",
        "needs_human": last.get("needs_human", "—") if last else "—",
        "next_due": last.get("next_due") or "—",
        "state": "awaiting your read" if pending else "due" if due else "waiting",
    }


def format_harness(record: dict) -> str:
    h = record.get("harness") if isinstance(record.get("harness"), dict) else {}
    links = []
    for link in h.get("tracking") or []:
        if not isinstance(link, dict):
            continue
        rules = _bullets(
            f"`{r.get('variable')}` {r.get('if')} → {r.get('means')}: {r.get('say')}"
            for r in link.get("rules") or [] if isinstance(r, dict)
        )
        variables = ", ".join(f"`{v}`" for v in link.get("variables") or []) or (
            f"none yet ({link['variable_gap']})" if link.get("variable_gap") else "none"
        )
        links.append(_join(
            f"**`{link.get('id')}`** ({link.get('runner')}): {link.get('must_hold')}",
            f"Variables: {variables} · expected: {link.get('expected_by') or link.get('expected_note') or '—'}",
            f"If late: {link['if_late']}" if link.get("if_late") else "",
            f"If against: {link['if_against']}" if link.get("if_against") else "",
            rules or "_No rules yet: this link reports no data until you add them._",
        ))
    wrong = _bullets(
        f"`{w.get('id')}` ({w.get('type')}): {w.get('label')}" for w in h.get("wrong_if") or [] if isinstance(w, dict)
    )
    baseline = record.get("baseline") if isinstance(record.get("baseline"), dict) else None
    return _join(
        f"## {record.get('title') or record.get('id')} (`{record.get('id')}`)",
        f"**Hypothesis:** {h.get('hypothesis')}",
        f"**Why:** {h.get('why')}",
        f"**Differs from:** {h['differs_from']}" if h.get("differs_from") else "",
        _section("Tracking", "\n\n".join(links)),
        _section("Wrong if", wrong),
        f"Baseline taken {baseline.get('taken_at')}." if baseline else "No baseline yet: the first check sets one.",
        "Stored only on this machine. EquityLayer keeps no copy.",
    )


def format_saved(record: dict, created: bool, warnings: list[str], path: str = "") -> str:
    verb = "Saved" if created else "Updated"
    return _join(
        f"**{verb} `{record.get('id')}`** ({record.get('title')}) on this machine"
        + (f" at `{path}`" if path else "") + ". EquityLayer keeps no copy.",
        _section("Check before relying on it", _bullets(warnings)),
        f"Next: `/el check {record.get('id')}` to read every link now, or `/el schedule` to check it daily.",
    )


__all__ = [
    "BOUNDARY",
    "format_check",
    "format_harness",
    "format_harness_list",
    "format_plan",
    "format_saved",
    "format_variable",
    "list_row",
]
