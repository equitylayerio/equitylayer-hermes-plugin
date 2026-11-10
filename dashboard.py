"""A local, self-contained HTML dashboard of the person's watchlists and theses.

Rendered by code from the local files only, so every agent produces the same page and no field is
written by a model. It contacts no one: no scripts, no external fonts, no remote images.
"""

from __future__ import annotations

import html
import re
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .harness_store import TAIPEI, is_due
from .profile_store import describe
from .watch_store import is_watch_due

FILE_NAME = "dashboard.html"
STATUS_TEXT = {"seen": "seen", "against": "against", "late": "late", "no_data": "no data", "not_due": "not due"}


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _https(url: Any) -> str | None:
    return url if isinstance(url, str) and url.startswith("https://") and len(url) < 500 else None


def _num(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "—"
    if isinstance(value, (int, float)):
        return f"{value:,.1f}".rstrip("0").rstrip(".") if isinstance(value, float) else f"{value:,}"
    return _e(value)


def _spark(values: list[Any]) -> str:
    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(nums) < 2:
        return ""
    lo, hi = min(nums), max(nums)
    span = (hi - lo) or 1.0
    w, h = 96, 24
    step = w / (len(nums) - 1)
    points = " ".join(f"{i * step:.1f},{h - 2 - (n - lo) / span * (h - 4):.1f}" for i, n in enumerate(nums))
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
            f'<polyline points="{points}" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>')


STEP_ORDER = ("material", "component", "optical_component", "optical_engine", "optical_module", "module",
              "package", "packaging", "chip", "switch", "system", "server", "network", "datacenter")


def _step_label(position: Any) -> str:
    """'network.optical_component' -> 'Optical component'. Only the catalog's own field, no added roles."""
    last = str(position or "").split(".")[-1].replace("_", " ").strip()
    return last[:1].upper() + last[1:] if last else "Other"


def _step_key(position: Any) -> tuple:
    last = str(position or "").split(".")[-1]
    return (STEP_ORDER.index(last) if last in STEP_ORDER else len(STEP_ORDER), last)


def _company(row: dict) -> str:
    name = str(row.get("name") or row.get("variable") or "")
    return (name.split(" (")[0] if " (" in name else name.split(" ")[0]).strip() or str(row.get("entity") or "")


def _chain_strip(rows: list[dict]) -> str:
    steps: dict[str, list[str]] = {}
    for row in sorted(rows, key=lambda r: _step_key(r.get("chain_position"))):
        names = steps.setdefault(_step_label(row.get("chain_position")), [])
        if _company(row) not in names:
            names.append(_company(row))
    if len(steps) < 1 or all(k == "Other" for k in steps):
        return ""
    boxes = '<span class="arrow" aria-hidden="true">→</span>'.join(
        f'<div class="step"><div class="step-name">{_e(step)}</div>'
        f'<div class="step-cos">{"".join(f"<span class=badge>{_e(n)}</span>" for n in names)}</div></div>'
        for step, names in steps.items())
    companies = len({_company(r) for r in rows})
    return (f'<div class="chain"><div class="muted small">Supply chain covered: {companies} companies, '
            f'{len(steps)} step(s)</div><div class="steps">{boxes}</div></div>')


def _watch_card(record: dict) -> str:
    last = record.get("last_check") if isinstance(record.get("last_check"), dict) else None
    unread = isinstance(record.get("pending"), dict)
    head = (f'<div class="card-head"><h3>{_e(record.get("title"))}</h3>'
            f'<span class="tag{" warn" if unread else ""}">{"unread" if unread else ("due" if is_watch_due(record) else "up to date")}</span></div>')
    if not last:
        return f'<section class="card">{head}<p class="muted">Not checked yet. Ask Hermes to check this watchlist.</p></section>'
    rows = []
    previous_step = None
    ordered = sorted(last.get("rows") or [], key=lambda r: _step_key(r.get("chain_position")))
    grouped = any(r.get("chain_position") for r in ordered)
    for r in ordered:
        step = _step_label(r.get("chain_position"))
        if grouped and step != previous_step:
            rows.append(f'<tr class="grp"><td colspan="5">{_e(step)}</td></tr>')
            previous_step = step
        latest = r.get("latest") or {}
        reading = (f'withheld ({_e(str(latest.get("withheld")).replace("_", " "))})' if latest.get("withheld")
                   else f'{_num(latest.get("value"))} <span class="unit">{_e(r.get("unit"))}</span>')
        new = '<span class="dot" title="new since you last read">●</span>' if r.get("new") else ""
        rows.append(
            f'<tr><td>{new}{_e(r.get("name"))}<div class="caveat">{_e(r.get("caveat"))}</div></td>'
            f'<td class="num">{reading}<div class="muted">{_e(latest.get("period"))}</div></td>'
            f'<td class="num">{_e(r.get("change"))}</td><td>{_spark(r.get("recent") or [])}</td>'
            f'<td class="muted num">{_e(r.get("next_reading"))}</td></tr>')
    table = ('<div class="tbl"><table><thead><tr><th>Reading</th><th>Latest</th><th>Change</th><th>Recent</th><th>Next</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div>')
    new = last.get("new_count", 0)
    new_part = f" · {_e(new)} new" if new is not None else ""
    return (f'<section class="card">{head}<p class="muted">Checked {_e(last.get("as_of"))}{new_part} · '
            f'next check {_e(last.get("next_due"))}</p>{_chain_strip(ordered)}{table}</section>')


def _thesis_card(record: dict) -> str:
    harness = record.get("harness") if isinstance(record.get("harness"), dict) else {}
    last = record.get("last_check") if isinstance(record.get("last_check"), dict) else None
    unread = isinstance(record.get("pending_baseline"), dict)
    tag = "unread" if unread else ("due" if is_due(record) else "up to date")
    head = (f'<div class="card-head"><h3>{_e(record.get("title"))}</h3>'
            f'<span class="tag{" warn" if unread else ""}">{tag}</span></div>'
            f'<p class="hyp">{_e(harness.get("hypothesis"))}</p>')
    if not last:
        return f'<section class="card">{head}<p class="muted">Not checked yet.</p></section>'
    chips = "".join(f'<span class="chip s-{_e(status)}">{_e(link)}: {_e(STATUS_TEXT.get(status, status))}</span>'
                    for link, status in (last.get("links") or {}).items())
    fired = last.get("wrong_if_fired") or []
    alerts = []
    if fired:
        alerts.append(f'<p class="alert">wrong_if fired: {_e(", ".join(str(f) for f in fired))}</p>')
    if last.get("needs_human"):
        alerts.append(f'<p class="alert">Needs you: {_e(last.get("needs_human"))} item(s)</p>')
    return (f'<section class="card">{head}<p class="muted">Checked {_e(last.get("as_of"))} · next due '
            f'{_e(last.get("next_due") or "—")}</p><div class="chips">{chips}</div>{"".join(alerts)}</section>')


def render(profile: dict | None, theses: list[dict], watchlists: list[dict], now: datetime | None = None,
           preview: dict | None = None) -> str:
    stamp = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).strftime("%Y-%m-%d %H:%M Taipei")
    about = describe(profile)
    needs = []
    for record in theses:
        last = record.get("last_check") if isinstance(record.get("last_check"), dict) else {}
        if isinstance(record.get("pending_baseline"), dict) or last.get("needs_human") or last.get("wrong_if_fired"):
            needs.append(f'<li>Thesis <b>{_e(record.get("title"))}</b>: '
                         + ", ".join(x for x in (
                             "unread check" if isinstance(record.get("pending_baseline"), dict) else "",
                             f'{_e(last.get("needs_human"))} item(s) only you can judge' if last.get("needs_human") else "",
                             "a wrong_if fired" if last.get("wrong_if_fired") else "") if x) + "</li>")
    for record in watchlists:
        if isinstance(record.get("pending"), dict):
            new = ((record.get("last_check") or {}).get("new_count") or 0)
            needs.append(f'<li>Watchlist <b>{_e(record.get("title"))}</b>: {_e(new)} new reading(s) to read</li>')
    events: dict[str, dict] = {}
    upcoming: list[dict] = []
    sources: list[str] = []
    for record in watchlists:
        last = record.get("last_check") if isinstance(record.get("last_check"), dict) else {}
        for event in last.get("events") or []:
            if isinstance(event, dict) and event.get("id"):
                events[event["id"]] = event
        upcoming += [u for u in last.get("upcoming") or [] if isinstance(u, dict)]
        for row in last.get("rows") or []:
            sources += [a for a in row.get("attribution") or [] if a not in sources]
    event_items = "".join(
        f'<li><span class="muted">{_e(e.get("at"))}</span> {_e(e.get("title"))}'
        + (f' · <a href="{_e(_https(e.get("url")))}">source</a>' if _https(e.get("url")) else "") + "</li>"
        for e in sorted(events.values(), key=lambda e: str(e.get("at") or ""), reverse=True)[:10])
    seen_up = set()
    up_items = ""
    for u in sorted(upcoming, key=lambda u: str(u.get("date") or "")):
        key = (u.get("date"), u.get("names"))
        if key in seen_up:
            continue
        seen_up.add(key)
        up_items += f'<li><span class="muted">{_e(u.get("date"))}</span> {_e(u.get("names"))}: {_e(u.get("reason"))}</li>'
    empty = not theses and not watchlists and not preview
    body = [
        f'<header><h1>Your EquityLayer research</h1><p class="muted">Updated {_e(stamp)}'
        + (f" · {_e(about)}" if about else "") + "</p></header>",
    ]
    if empty:
        body.append('<section class="card"><p>Nothing tracked yet. In Hermes, type <code>/equitylayer:start</code>.</p></section>')
    if preview:
        card = _watch_card({"title": preview.get("title"), "pending": None,
                            "last_check": {"as_of": preview.get("as_of"), "rows": preview.get("rows") or [],
                                           "new_count": None, "next_due": "after you save"}})
        card = re.sub(r'<span class="tag[^"]*">[^<]*</span>', '<span class="tag">preview, not saved</span>', card, count=1)
        actions = ('<div class="actions">'
                   '<button type="button" data-hermes-send="Yes, follow these curated readings.">Follow these readings</button>'
                   '<button type="button" class="ghost" data-hermes-send="I have my own view.">I have my own view</button>'
                   '</div>')
        body.append("<h2>Live now</h2>" + card + actions)
        for row in preview.get("rows") or []:
            sources += [a for a in row.get("attribution") or [] if a not in sources]
    if needs:
        body.append(f'<section class="card needs"><h2>Needs you</h2><ul>{"".join(needs)}</ul></section>')
    if watchlists:
        body.append("<h2>Following</h2>" + "".join(_watch_card(r) for r in watchlists))
    if theses:
        body.append("<h2>Your theses</h2>" + "".join(_thesis_card(r) for r in theses))
    if event_items:
        body.append(f'<section class="card"><h2>Recent events</h2><ul>{event_items}</ul></section>')
    if up_items:
        body.append(f'<section class="card"><h2>Coming up</h2><ul>{up_items}</ul></section>')
    if sources:
        body.append('<section class="card"><h2>Sources</h2><ul class="small">'
                    + "".join(f"<li>{_e(s)}</li>" for s in sources[:12]) + "</ul></section>")
    body.append('<footer class="muted small">Generated on this machine from your local files. EquityLayer reports '
                "what moved and stops: nothing here says what to buy, sell, size or time. Not investment advice.</footer>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EquityLayer research</title>
<style>
:root{{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;--accent:#2f5bd3;--warn:#b4541a;
--seen:#2e7d4f;--against:#b3261e;--late:#b4541a;--nodata:#8a8a85}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151514;--card:#1f1f1d;--ink:#ececea;--muted:#a3a39d;--line:#33332f;
--accent:#8fb0ff;--warn:#f0a066;--seen:#6fcf97;--against:#ff8a80;--late:#f0a066;--nodata:#9a9a94}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,system-ui,Segoe UI,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:24px 16px 48px}}h1{{font-size:24px;margin:0 0 4px}}h2{{font-size:17px;margin:28px 0 10px}}
h3{{font-size:16px;margin:0}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}}
.card h2{{margin-top:0}}.card-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
.tag{{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}}.tag.warn{{color:var(--warn);border-color:var(--warn)}}
.muted{{color:var(--muted)}}.small{{font-size:13px}}.unit{{color:var(--muted);font-size:12px}}.caveat{{color:var(--muted);font-size:12px}}
.hyp{{margin:6px 0}}table{{width:100%;border-collapse:collapse;margin-top:8px}}th,td{{text-align:left;padding:8px 6px;border-top:1px solid var(--line);vertical-align:top}}
th{{font-size:12px;color:var(--muted);font-weight:600}}.num{{white-space:nowrap}}.dot{{color:var(--accent);margin-right:6px}}.spark{{color:var(--accent)}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}.chip{{font-size:12px;padding:2px 8px;border-radius:99px;border:1px solid var(--line)}}
.s-seen{{color:var(--seen)}}.s-against{{color:var(--against)}}.s-late{{color:var(--late)}}.s-no_data,.s-not_due{{color:var(--nodata)}}
.chain{{margin:10px 0 4px}}.steps{{display:flex;flex-wrap:wrap;align-items:stretch;gap:6px;margin-top:6px}}.step{{border:1px solid var(--line);border-radius:8px;padding:8px 10px;min-width:140px;flex:1}}.step-name{{font-weight:600;font-size:13px;margin-bottom:6px}}.step-cos{{display:flex;flex-wrap:wrap;gap:4px}}.badge{{font-size:12px;padding:1px 7px;border-radius:99px;background:var(--bg);border:1px solid var(--line)}}.arrow{{align-self:center;color:var(--muted)}}tr.grp td{{font-size:12px;font-weight:600;color:var(--muted);background:var(--bg);padding:6px}}@media (max-width:640px){{.arrow{{display:none}}.step{{min-width:100%}}}}.actions{{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 0}}.actions button{{font:inherit;font-size:14px;padding:8px 14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer}}.actions button.ghost{{background:transparent;color:var(--accent)}}.alert{{color:var(--warn);margin:8px 0 0}}.needs{{border-color:var(--warn)}}a{{color:var(--accent)}}footer{{margin-top:28px}}
.tbl{{overflow-x:auto}}@media (max-width:640px){{th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){{display:none}}.num{{white-space:normal}}td:first-child{{min-width:9em}}}}
</style></head><body><main>
{"".join(body)}
</main></body></html>
"""


def write(root: Path, page: str) -> Path:
    path = Path(root) / FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".html")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(page)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
