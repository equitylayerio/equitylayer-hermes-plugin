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
# Where each sector's public page lives; the dashboard links there as the way to EquityLayer's own research.
SECTOR_PAGES = {
    "optical_cpo": "https://equitylayer.io/sectors/cpo",
    "custom_asic": "https://equitylayer.io/sectors/asic",
    "space_infrastructure": "https://equitylayer.io/sectors/space",
    "physical_ai": "https://equitylayer.io/themes/physical-ai",
}
SITE = "https://equitylayer.io"
PACK_PAGE = "https://equitylayer.io/research/packs/"
AI_COMPUTE_MAP = "https://equitylayer.io/themes/ai-compute"
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


def _step_label(row: dict) -> str:
    """The company's own supply-chain step when we have it; else the catalog's chain_position."""
    company = row.get("company") if isinstance(row.get("company"), dict) else None
    if company and company.get("step"):
        return str(company["step"])
    last = str(row.get("chain_position") or "").split(".")[-1].replace("_", " ").strip()
    return last[:1].upper() + last[1:] if last else "Other"


def _step_key(row: dict) -> tuple:
    company = row.get("company") if isinstance(row.get("company"), dict) else None
    if company and company.get("step"):
        return (0, int(company.get("step_order") or 99), str(company["step"]))
    last = str(row.get("chain_position") or "").split(".")[-1]
    return (1, STEP_ORDER.index(last) if last in STEP_ORDER else len(STEP_ORDER), last)


def _company(row: dict) -> str:
    name = str(row.get("name") or row.get("variable") or "")
    return (name.split(" (")[0] if " (" in name else name.split(" ")[0]).strip() or str(row.get("entity") or "")


def _signal(row: dict) -> str:
    category = str(row.get("category") or "")
    name = str(row.get("name") or "").lower()
    if category == "demand":
        return "Demand"
    if category == "margin":
        return "Pricing"
    if category == "cash":
        return "Capacity" if "property" in name or "capex" in name else "Cash flow"
    if category == "revenue":
        return "Revenue pulse" if row.get("cadence") == "monthly" else "Revenue"
    return ""


def _signal_tag(row: dict) -> str:
    label = _signal(row)
    return f'<span class="sig">{_e(label)}</span> ' if label else ""


def _role_line(row: dict) -> str:
    company = row.get("company") if isinstance(row.get("company"), dict) else None
    if not company or not company.get("role"):
        return ""
    link = _https(company.get("source_url"))
    if link:
        source = f' <a href="{_e(link)}">source</a>'
    else:  # an issuer site that only serves plain HTTP: name it, don't link it
        source = f' <span class="muted">(source: {_e(company.get("source_title") or company.get("source_url"))})</span>'
    return f'<div class="role">{_e(company["role"])}{source}</div>'


def _chain_strip(rows: list[dict]) -> str:
    steps: dict[str, list[str]] = {}
    roles: dict[str, str] = {}
    for row in sorted(rows, key=_step_key):
        names = steps.setdefault(_step_label(row), [])
        if _company(row) not in names:
            names.append(_company(row))
        if isinstance(row.get("company"), dict):
            roles[_company(row)] = row["company"].get("role") or ""
    if len(steps) < 1 or all(k == "Other" for k in steps):
        return ""
    def badge(name: str) -> str:
        return f'<span class="badge" title="{_e(roles.get(name, ""))}">{_e(name)}</span>'

    boxes = '<span class="arrow" aria-hidden="true">→</span>'.join(
        f'<div class="step"><div class="step-name">{_e(step)}</div>'
        f'<div class="step-cos">{"".join(badge(n) for n in names)}</div></div>'
        for step, names in steps.items())
    companies = len({_company(r) for r in rows})
    return (f'<div class="chain"><div class="muted small">Supply chain covered: {companies} companies, '
            f'{len(steps)} step(s)</div><div class="steps">{boxes}</div></div>')


def _watch_card(record: dict) -> str:
    last = record.get("last_check") if isinstance(record.get("last_check"), dict) else None
    unread = isinstance(record.get("pending"), dict)
    title = record.get("title")
    shown = f"Readings for: {_short_name(title)}" if record.get("follow_id") and title != _short_name(title) else title
    head = (f'<div class="card-head"><h3>{_e(shown)}</h3>'
            f'<span class="tag{" warn" if unread else ""}">{"unread" if unread else ("due" if is_watch_due(record) else "up to date")}</span></div>')
    if not last:
        return f'<section class="card">{head}<p class="muted">Not checked yet. Ask Hermes to check this watchlist.</p></section>'
    rows = []
    previous_step = None
    ordered = sorted(last.get("rows") or [], key=_step_key)
    grouped = any(r.get("chain_position") or r.get("company") for r in ordered)
    for r in ordered:
        step = _step_label(r)
        if grouped and step != previous_step:
            rows.append(f'<tr class="grp"><td colspan="5">{_e(step)}</td></tr>')
            previous_step = step
        latest = r.get("latest") or {}
        reading = (f'withheld ({_e(str(latest.get("withheld")).replace("_", " "))})' if latest.get("withheld")
                   else f'{_num(latest.get("value"))} <span class="unit">{_e(r.get("unit"))}</span>')
        new = '<span class="dot" title="new since you last read">●</span>' if r.get("new") else ""
        about = _role_line(r) + (f'<div class="caveat">{_e(r.get("caveat"))}</div>' if r.get("caveat") else "")
        wordy = isinstance(latest.get("value"), str) and not latest.get("withheld")
        rows.append(
            f'<tr><td>{new}{_signal_tag(r)}{_e(r.get("name"))}'
            + (f'<details class="row-more"><summary>About this reading</summary>{about}</details>' if about else "")
            + '</td>'
            f'<td class="{"txt" if wordy else "num"}">{reading}<div class="muted">{_e(latest.get("period"))}</div></td>'
            f'<td class="num">{_e(r.get("change"))}</td><td>{_spark(r.get("recent") or [])}</td>'
            f'<td class="muted num">{_e(r.get("next_reading"))}</td></tr>')
    table = ('<details class="more" open><summary>All readings</summary><div class="tbl"><table><thead><tr><th>Reading</th><th>Latest</th><th>Change</th><th>Recent</th><th>Next</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table></div></details>')
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


def _verdict(last: dict) -> tuple[str, str]:
    """A plain status for the thesis from the harness check. It describes the evidence, not a trade."""
    counts = last.get("counts") or {}
    if last.get("wrong_if_fired"):
        return "A wrong_if condition fired", "against"
    if counts.get("against") or counts.get("late"):
        return "Under pressure", "late"
    if last.get("needs_human"):
        return "Needs your judgment", "warn"
    if counts.get("seen"):
        return "Holding so far", "seen"
    return "Waiting for readings", "no_data"


def _thesis_hero(record: dict) -> str:
    harness = record.get("harness") if isinstance(record.get("harness"), dict) else {}
    last = record.get("last_check") if isinstance(record.get("last_check"), dict) else None
    status = ""
    if last:
        verdict, tone = _verdict(last)
        counts = last.get("counts") or {}
        parts = [f'{counts.get(k, 0)} {STATUS_TEXT[k]}' for k in ("seen", "against", "late", "no_data", "not_due") if counts.get(k)]
        status = (f'<p><span class="verdict v-{_e(tone)}">{_e(verdict)}</span></p>'
                  f'<p class="muted">Links: {_e(" · ".join(parts) or "none checked")}'
                  f' · wrong_if fired: {_e(len(last.get("wrong_if_fired") or []))}'
                  f' · next check {_e(last.get("next_due") or "—")}</p>')
    else:
        status = '<p class="muted">Not checked yet.</p>'
    return (f'<section class="card hero"><p class="eyebrow">Your thesis · {_e(record.get("title"))}</p>'
            f'<p class="hero-text">{_e(harness.get("hypothesis"))}</p>{status}</section>')


SHORT_THEMES = {"optical_cpo": "CPO", "custom_asic": "ASIC", "space_infrastructure": "Space", "physical_ai": "Physical AI"}


def _short_claim(text: Any, limit: int = 130) -> str:
    """The claim part of a hypothesis: the clause before its explanation, kept to one line or two."""
    text = " ".join(str(text or "").split())
    head = text.split(": ", 1)[0] if ": " in text[:limit + 20] else text
    return _clip(head, limit)


def _band(rules: list[dict], value: Any) -> dict | None:
    """Which of a Pack's reading rules the latest value falls in: '>= x', '> x', '<= x', '< x' or 'a..b'."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for rule in rules or []:
        cond = str(rule.get("if") or "").replace(",", "").strip()
        try:
            if ".." in cond:
                lo, hi = (float(x) for x in cond.split("..", 1))
                hit = lo <= v <= hi
            elif cond.startswith(">="):
                hit = v >= float(cond[2:])
            elif cond.startswith("<="):
                hit = v <= float(cond[2:])
            elif cond.startswith(">"):
                hit = v > float(cond[1:])
            elif cond.startswith("<"):
                hit = v < float(cond[1:])
            else:
                continue
        except ValueError:
            continue
        if hit:
            return rule
    return None


MEANS = {"strengthens": ("up", "supports"), "weakens": ("down", "weakens"), "fires": ("down", "breaks")}


def _cond(cond: Any) -> str:
    """A rule's condition with readable numbers: '>= 540492' becomes '≥ 540,492'."""
    import re as _re

    text = str(cond or "").replace("..", " to ").replace(">=", "≥ ").replace("<=", "≤ ")
    return _re.sub(r"\d{4,}(?:\.\d+)?", lambda m: _num(float(m.group(0))), text).replace("  ", " ").strip()


def _var_chip(row: dict, rule: dict | None = None) -> str:
    """A tracked variable as one short chip: company, latest value, change."""
    latest = row.get("latest") or {}
    if latest.get("withheld"):
        value = "withheld"
    elif isinstance(latest.get("value"), str):
        value = f'statement {latest.get("period") or ""}'.strip()
    elif latest.get("value") is not None:
        value = _num(latest.get("value"))
    else:
        value = "no data yet"
    change = str(row.get("change") or "").split(" vs ")[0]
    tone = "up" if change.startswith("+") else ("down" if change.startswith("-") or change.startswith("−") else "")
    tone_cls = MEANS.get(str((rule or {}).get("means")), ("flat", "no verdict yet"))[0] if rule else ""
    return (f'<span class="chip {tone_cls}" title="{_e(row.get("name"))} · {_e(latest.get("period"))} · {_e(row.get("unit"))}">'
            f'{_e(_company(row))} <b>{_e(value)}</b>'
            + (f' <span class="chg {tone}">{_e(change)}</span>' if change else "") + "</span>")


def _next_items(record: dict, rows: list[dict], today: str | None = None) -> list[str]:
    """What changes next, by date. A date that passed without the data says so instead of looking upcoming."""
    from .harness_store import today_taipei

    today = today or today_taipei()
    by_date: dict[str, list[str]] = {}
    for row in rows:
        when = str(row.get("next_reading") or "")
        if len(when) >= 10:
            names = by_date.setdefault(when[:10], [])
            if _company(row) not in names:
                names.append(_company(row))
    events = [(day, f'<span class="nx{" late" if day < today else ""}"><b>{_e(day[5:])}</b> '
                    + ("late: " if day < today else "") + f'{_e(", ".join(names))}</span>')
              for day, names in by_date.items()]
    check = str(record.get("next_check_at") or record.get("fresh_until") or "")[:10]
    if check:
        events.append((check, f'<span class="nx"><b>{_e(check[5:])}</b> Pack check</span>'))
    return [h for _, h in sorted(events)[:4]] + ['<a class="tc-cal" href="calendar.ics">Add these dates to your calendar</a>']


def _pack_hero(record: dict, compact: bool = False, open_: bool = True, readings: dict | None = None,
               letter: str | None = None) -> str:
    """A followed Pack as a scoreboard: the thesis, then one compact row per hypothesis (claim, the numbers it
    tracks, when it is tested, and what would prove it wrong), then what changes next. Details sit behind hover
    and the full Pack link."""
    summary = record.get("pack") if isinstance(record.get("pack"), dict) else {}
    theme = SHORT_THEMES.get(summary.get("theme_id"), "")
    kind = "Tracking Pack" if summary.get("category") == "tracking" else "Thesis Pack"
    last = (readings or {}).get("last_check") if isinstance((readings or {}).get("last_check"), dict) else {}
    rows = [r for r in (last or {}).get("rows") or [] if isinstance(r, dict)]
    by_var = {r.get("variable"): r for r in rows}
    pending = record.get("pending_review") if isinstance(record.get("pending_review"), dict) else None
    badge = (f'<span class="tag warn">{"new revision to review" if pending.get("revision_changed") else "new data to read"}</span>'
             if pending else "")
    url = _https(summary.get("url"))
    core: list[tuple[str, str]] = []
    rest: list[tuple[str, str]] = []
    hyp_list = [h for h in (summary.get("hypotheses") or []) if isinstance(h, dict)][:8]
    for n, h in enumerate(hyp_list, 1):
        reads = h.get("reads") if isinstance(h.get("reads"), dict) else {}
        def judged(v: str) -> dict | None:
            """A rule only judges a reading that came after the Pack's baseline; the baseline itself proves nothing."""
            spec = reads.get(v) if isinstance(reads.get(v), dict) else {}
            latest = by_var[v].get("latest") or {}
            if not spec.get("baseline") or latest.get("period") == spec.get("baseline"):
                return None
            return _band(spec.get("rules") or [], latest.get("value"))

        found = [(by_var[v], judged(v)) for v in h.get("variables") or [] if v in by_var]
        chips = '<span class="tc-chips">' + "".join(_var_chip(row, rule) for row, rule in found) + "</span>" if found else ""
        verdicts = [str(rule.get("means")) for _, rule in found if rule]
        light = ("down" if any(m in ("weakens", "fires") for m in verdicts)
                 else "up" if verdicts and all(m == "strengthens" for m in verdicts) else "flat")
        light_text = {"down": "a tracked number weakens it", "up": "tracked numbers support it",
                      "flat": "no verdict yet"}[light]
        # One labelled line per question a reader has: what is tracked, why, what supports it, what breaks it,
        # what follows if it holds, and when the next number lands.
        def bars(kind: str) -> str:
            out = []
            for row, _ in found:
                spec = reads.get(row.get("variable")) if isinstance(reads.get(row.get("variable")), dict) else {}
                rule = next((r for r in spec.get("rules") or [] if str(r.get("means")) == kind), None) or {}
                cond = rule.get("if")
                if cond and str(cond).lstrip()[:1] in "<>=0123456789":
                    # Say where the bar comes from first; the exact figure is only its value.
                    say = str(rule.get("say") or "")
                    origin = say.split(":", 1)[0].strip() if ":" in say[:70] else say.split(".", 1)[0].strip()
                    if origin and len(origin) <= 60:
                        out.append(f"{_company(row)} {origin[:1].lower() + origin[1:]} ({_cond(cond)})")
                    else:
                        out.append(f"{_company(row)} {_cond(cond)}")
                elif cond:                      # a condition in words already names who and what
                    out.append(_clip(cond, 110))
            return " · ".join(out[:3])

        why = h.get("angle") or next(
            (r.get("say") for row, _ in found
             for r in ((reads.get(row.get("variable")) or {}).get("rules") or []) if isinstance(reads.get(row.get("variable")), dict)
             if str(r.get("means")) == "strengthens" and r.get("say")), None)
        sources = "".join(f'<a href="{_e(_https(row.get("source_url")))}">{_e(_company(row))}</a>'
                          for row, _ in found if _https(row.get("source_url")))
        dates = sorted({str(row.get("next_reading"))[:10] for row, _ in found if len(str(row.get("next_reading") or "")) >= 10})
        from .harness_store import today_taipei
        nxt = ""
        if dates:
            nxt = dates[0] + (" (late)" if dates[0] < today_taipei() else "")
        moves = "; ".join(f'{str(m.get("node")).split(".")[-1].replace("_", " ")}s {m.get("effect")[:-1]}'
                          for m in h.get("moves") or [] if isinstance(m, dict))
        wrong = h.get("falsifier")

        def line(key: str, value: str, cls: str = "", raw: bool = False, title: Any = None) -> str:
            if not value:
                return ""
            tip = f' title="{_e(title)}"' if title else ""
            return (f'<div class="kv {cls}"><span class="k">{_e(key)}</span>'
                    f'<span class="v"{tip}>{value if raw else _e(value)}</span></div>')

        role = str(h.get("role") or "core")
        item = (f'<li class="tc-item"><details{" open" if open_ and n == 1 else ""}><summary class="tc-row">'
                 f'<span class="tc-n">{_e(letter + "·") if letter else ""}H{n}</span>'
                 f'<span class="light {light}" title="{_e(light_text)}"></span>'
                 f'<span class="tc-claim" title="{_e(h.get("statement"))}">{_e(_short_claim(h.get("statement"), 90))}</span>'
                 f'<span class="tc-due">{_e(" · ".join(x for x in (role if role in ("supporting", "risk") else "", light_text if light != "flat" else "") if x))}</span></summary>'
                 + line("Most think", _clip(h.get("consensus"), 130))
                 + line("Why it matters", _clip(why, 130))
                 + line("Tracks", chips, raw=True)
                 + line("Supports if", bars("strengthens"), "good")
                 + line("Weakens if", bars("weakens"), "bad")
                 + line("Wrong if", _clip(wrong, 120), "bad", title=wrong)
                 + (line("If it holds", moves + " (per the Pack)", "good") if moves
                    else line("If it holds", "not stated in the Pack yet", "quiet"))
                 + line("Next", " · ".join(x for x in (f"data {nxt}" if nxt else "", f"tested by {h.get('due')}" if h.get("due") else "",
                                                       f"confidence {h.get('confidence')}" if h.get("confidence") else "") if x))
                 + line("Sources", sources, "src", raw=True)
                 + "</details></li>")
        (core if role == "core" else rest).append((role, item))
    # The core claims lead; supporting checks and risks wait one click away.
    body = f'<ol class="tc-list">{"".join(i for _, i in core)}</ol>' if core else ""
    if rest:
        kinds = [k for k, _ in rest]
        label = " · ".join(f"{kinds.count(k)} {k}" for k in ("supporting", "risk") if k in kinds) or f"{len(rest)} more"
        inner = f'<ol class="tc-list">{"".join(i for _, i in rest)}</ol>'
        body += (f'<details class="more tc-rest"><summary>+ {_e(label)}</summary>{inner}</details>' if core else inner)
    # Every hypothesis is one line you can open; only the first one of the first Pack starts open.
    nexts = _next_items(record, rows)
    return (f'<section class="card hero pack thesis-card"><div class="tc-head">'
            + (f'<span class="tc-letter">{_e(letter)}</span>' if letter else "")
            + f'<p class="eyebrow">{_e(kind)}'
            + (f" · {_e(theme)}" if theme else "") + "</p>" + badge
            + (f'<a class="tc-link" href="{_e(url)}" title="Read the full Pack on equitylayer.io">full Pack ↗</a>' if url else "")
            + f'</div><h3 class="tc-thesis" title="{_e(summary.get("view"))}">{_e(summary.get("title"))}</h3>'
            + body
            + (f'<div class="tc-next"><span class="tc-k">Next</span>{"".join(nexts)}</div>' if nexts else "")
            + "</section>")


def _change_pct(row: dict) -> float | None:
    match = re.match(r"^([+-]\d+(?:\.\d+)?)%", str(row.get("change") or ""))
    return float(match.group(1)) if match else None


def _readings_summary(record: dict | None) -> str:
    """One line on a followed Pack's card: how its readings moved, and the largest move."""
    last = (record or {}).get("last_check") if isinstance((record or {}).get("last_check"), dict) else None
    rows = (last or {}).get("rows") or []
    if not rows:
        return ""
    pcts = [(p, r) for r in rows if (p := _change_pct(r)) is not None]
    up = sum(1 for p, _ in pcts if p > 0.5)
    down = sum(1 for p, _ in pcts if p < -0.5)
    flat = len(pcts) - up - down
    top = max(pcts, key=lambda pr: abs(pr[0]))[1] if pcts else None
    biggest = f" · largest move {_e(_company(top))} {_e(top.get('change'))}" if top else ""
    return (f'<p class="pack-readings"><b>Its {len(rows)} readings:</b> {up} up, {down} down, {flat} flat'
            f'{biggest}. <a href="#evidence">See them below</a>.</p>')


def _readings_hero(record: dict, linked: bool = False) -> str:
    last = record.get("last_check") if isinstance(record.get("last_check"), dict) else None
    rows = (last or {}).get("rows") or []
    if not rows:
        return ""
    pcts = [(p, r) for r in rows if (p := _change_pct(r)) is not None]
    up = sum(1 for p, _ in pcts if p > 0.5)
    down = sum(1 for p, _ in pcts if p < -0.5)
    flat = len(pcts) - up - down
    withheld = sum(1 for r in rows if (r.get("latest") or {}).get("withheld"))
    movers = sorted(pcts, key=lambda pr: abs(pr[0]), reverse=True)[:3]
    items = "".join(f'<li>{_signal_tag(r)}{_e(_company(r))}: {_e(r.get("change"))}</li>' for _, r in movers)
    return (f'<section class="card hero"><p class="eyebrow">What your readings show · {_e(record.get("title"))}</p>'
            f'<p class="hero-text">{len(rows)} readings: {up} up, {down} down, {flat} flat against the period before'
            + (f", {withheld} withheld" if withheld else "") + '.</p>'
            + (f'<p class="muted small">Largest moves</p><ul class="movers">{items}</ul>' if items else "")
            + ('<p class="muted small">These are the readings the Pack above watches. Its hypotheses say what each '
               'would mean, and when.</p>' if linked else
               '<p class="muted small">This describes the readings, not a view. Add your own thesis to have Hermes '
               'check it.</p>')
            + '</section>')


THEME_LABELS = {"optical_cpo": "CPO and optical networking", "custom_asic": "Custom AI chips (ASIC)",
                "space_infrastructure": "Space infrastructure", "physical_ai": "Physical AI", "other": "Other"}
THEME_ORDER = ("optical_cpo", "custom_asic", "space_infrastructure", "physical_ai", "other")


def _theme_of(record: dict) -> str:
    theme = record.get("theme")
    if not theme and isinstance(record.get("harness"), dict):
        theme = record["harness"].get("theme_id") or record["harness"].get("theme")
    return theme if theme in THEME_LABELS else "other"


def _theme_label(theme: str) -> str:
    return THEME_LABELS.get(theme, "Other")


def _theme_order(theme: str) -> int:
    return THEME_ORDER.index(theme) if theme in THEME_ORDER else len(THEME_ORDER)


def _short_name(title: Any) -> str:
    """A Pack's readings list is named after the Pack; the sidebar only needs the Pack part."""
    text = str(title or "")
    marker = " Pack readings: "
    return text.split(marker, 1)[1] if marker in text else text


def _sidebar(groups: dict, watchlists: list[dict], preview: dict | None, needs: bool) -> str:
    items = ['<p class="side-label">Workspace</p><nav><a href="#glance">At a glance</a>']
    if preview:
        items.append('<a href="#live">Live now</a>')
    if needs:
        items.append('<a href="#needs">Needs you</a>')
    items.append('<a href="#events">Events and dates</a></nav>')
    if groups:
        items.append('<p class="side-label">Themes</p><nav>')
        for theme in sorted(groups, key=_theme_order):
            group = groups[theme]
            subs = [r.get("title") for r in group["watch"]] + [r.get("title") for r in group["theses"]]
            items.append(f'<a href="#theme-{_e(theme)}">{_e(_theme_label(theme))}</a>'
                         + "".join(f'<span class="side-sub" title="{_e(t)}">{_e(_short_name(t))}</span>'
                                   for t in subs[:4]))
        items.append("</nav>")
    companies: dict[str, str] = {}
    for record in watchlists:
        for row in ((record.get("last_check") or {}).get("rows") or []):
            companies.setdefault(_company(row), str(row.get("entity") or ""))
    for row in ((preview or {}).get("rows") or []):
        companies.setdefault(_company(row), str(row.get("entity") or ""))
    if companies:
        items.append('<p class="side-label">Companies</p><nav class="cos">')
        items += [f'<span class="side-co">{_e(name)}<small>{_e(ent)}</small></span>' for name, ent in list(companies.items())[:16]]
        items.append("</nav>")
    items.append('<p class="side-foot">Saved on this machine</p>')
    return f'<aside class="side">{"".join(items)}</aside>'


def _clip(text: Any, limit: int = 280) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


PACK_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
# EquityLayer's Pack categories (closed list). No field means a thesis Pack, but the label shows only when given.
CATEGORY_LABELS = {"thesis": "Thesis Pack", "tracking": "Tracking Pack"}


def _pack_id(value: Any) -> str | None:
    """Registry ids go into a chat message and a URL, so only plain slugs are used."""
    return value if isinstance(value, str) and PACK_ID.match(value) else None


def _pack_url(entry: dict) -> str | None:
    pid = _pack_id(entry.get("id"))
    return _https(entry.get("url")) or (PACK_PAGE + pid if pid else None)


def _pack_cards(themes: list[str], packs: list[dict] | None, followed: dict[str, dict],
                packs_as_of: str | None = None, skip: set[str] | None = None) -> list[str]:
    """One card per sector: a Pack the user follows, a published Pack they can follow, or where the sector stands.

    `packs` is the last registry the plugin saw (None when it has never seen one). A sector with no listed Pack only
    says that none is published; whether one is coming is the sector page's to say.
    """
    cards, shown = [], set(skip or ())
    entries, seen_ids = [], set()
    for p in packs or []:
        if isinstance(p, dict) and p.get("kind") == "pack" and p.get("id") and p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            entries.append(p)
    for pid in followed:
        if pid not in seen_ids:
            entries.append({"id": pid, "kind": "pack", "title": pid, "theme_id": None})
    ordered = list(dict.fromkeys(themes + [p.get("theme_id") for p in entries
                                           if p["id"] in followed and p.get("theme_id")]))
    as_of = f"Registry as of {packs_as_of}." if packs_as_of else ""
    for theme in ordered:
        mine = [p for p in entries if p.get("theme_id") == theme]
        label = _theme_label(theme)
        page = SECTOR_PAGES.get(theme, SITE)
        heroes = [p for p in mine if p["id"] in (skip or ())]
        mine_followed = [p for p in mine if p["id"] in followed and p["id"] not in shown]
        published = [p for p in mine if p["id"] not in followed and p.get("status") == "verified"
                     and p.get("access") == "public" and _pack_id(p.get("id"))]
        for p in (mine_followed + published)[:6]:
            shown.add(p["id"])
            cards.append(_pack_card(p, label, followed.get(p["id"]), as_of))
        if heroes or mine_followed or published:
            continue
        restricted = [p for p in mine if p.get("status") == "verified" and p.get("access") != "public"]
        review = [p for p in mine if p.get("status") == "in_review"]
        if restricted:
            text = (f'{_e(restricted[0].get("title"))} is published with restricted access. This plugin reads public '
                    'Packs only.')
        elif review:
            text = (f'{_e(review[0].get("title"))} is in review, not published yet. It can be read and followed '
                    'once it is published.')
        elif packs is not None:
            text = ("EquityLayer has not published a Research Pack for this sector. Its industry map shows which "
                    "segments it tracks and where a Pack stands.")
        else:
            text = ("EquityLayer's research for this sector is on equitylayer.io: the industry map, the segments it "
                    "tracks and any published Research Pack.")
        cards.append(f'<section class="card pack"><p class="eyebrow">Research Pack · {_e(label)}</p>'
                     f'<p>{text}</p>' + (f'<p class="muted small">{_e(as_of)}</p>' if as_of and packs is not None else "")
                     + f'<p><a class="go" href="{_e(page)}">Open on equitylayer.io →</a></p></section>')
    for p in entries:
        if p["id"] in followed and p["id"] not in shown:
            shown.add(p["id"])
            cards.append(_pack_card(p, None, followed[p["id"]], as_of))
    return cards


def _pack_card(entry: dict, label: str | None, follow: dict | None, as_of: str = "") -> str:
    state = "you follow it" if follow is not None else "published"
    kind = CATEGORY_LABELS.get(entry.get("category") or ((follow or {}).get("pack") or {}).get("category"))
    eyebrow = (kind or "Research Pack") + (f" · {label}" if label else "") + f" · {state}"
    parts = [f'<section class="card pack"><p class="eyebrow">{_e(eyebrow)}</p>',
             f'<h3>{_e(entry.get("title") or entry.get("id"))}</h3>']
    if entry.get("view"):
        parts.append(f'<p class="tc-view" title="{_e(as_of)}">{_e(_clip(entry["view"], 160))}</p>')
    url = _pack_url(entry)
    link = f'<a class="go" href="{_e(url)}">Read it on equitylayer.io →</a>' if url else ""
    if follow is not None:
        due = follow.get("next_check_at") or follow.get("fresh_until")
        if follow.get("pending_review"):
            parts.append('<p class="muted small">An update to this Pack is waiting for your review. Ask Hermes to '
                         'check it.</p>')
        else:
            parts.append('<p class="muted small">Checked with your other items' + (f"; next check {_e(due)}" if due else "")
                         + '. Hermes shows you when the Pack changes.</p>')
        parts.append(f"<p>{link}</p>" if link else "")
    else:
        pid = _pack_id(entry.get("id"))
        parts.append('<div class="actions">'
                     + (f'<button type="button" data-hermes-send="Follow the EquityLayer Research Pack {pid}.">'
                        'Follow this Pack</button>' if pid else "")
                     + link + "</div>")
    return "".join(parts) + "</section>"


# The full chain each sector is drawn on, left to right (company_roles.json steps, in order).
SECTOR_STEPS = {
    "optical_cpo": ["Epitaxy wafers", "Lasers and optical modules", "Passive optics and fiber arrays",
                    "Optical modules and transceivers", "Contract manufacturing", "Optical networking systems"],
}


def _wrap(text: str, width: int = 15) -> list[str]:
    words, lines, line = str(text).split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width and line:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        lines.append(line)
    return lines[:3]


def _chain_3d(theme: str, packs: list[tuple[str, dict, list[dict]]]) -> str:
    """The sector's supply chain and where the followed theses sit on it (SVG, no script).

    Steps stand left to right on one platform. A step with a tracked company under a hypothesis is a tall, filled
    block with a pin naming the Pack and hypotheses (for example "B · H1 H2"); other steps stay low and pale.
    Under each block: the step's name and the companies tracked there."""
    marks: dict[str, dict[str, list[int]]] = {}
    companies: dict[str, list[str]] = {}
    extra: list[tuple[tuple, str]] = []
    for letter, summary, rows in packs:
        for row in rows:
            step = _step_label(row)
            names = companies.setdefault(step, [])
            if _company(row) not in names:
                names.append(_company(row))
            extra.append((_step_key(row), step))
        by_var = {r.get("variable"): r for r in rows}
        for n, h in enumerate([h for h in summary.get("hypotheses") or [] if isinstance(h, dict)], 1):
            for v in h.get("variables") or []:
                row = by_var.get(v)
                if row:
                    nums = marks.setdefault(_step_label(row), {}).setdefault(letter, [])
                    if n not in nums:
                        nums.append(n)
    if not companies:
        return ""
    steps = list(SECTOR_STEPS.get(theme, []))
    for _, step in sorted(extra):
        if step not in steps:
            steps.append(step)
    steps = steps[:8]

    w, gap, d, pad, thick = 84, 20, 17, 30, 9
    hw = w / 2
    base = 78 + d + 40                      # ground line of the blocks
    width = pad * 2 + len(steps) * w + (len(steps) - 1) * gap
    left, right, half = pad - 14, width - pad + 14, d + 8
    run = half * hw / d                     # keeps the platform's edges parallel to the blocks'

    def pts(*xy: tuple[float, float]) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in xy)

    out = [
        # the platform everything stands on
        f'<polygon class="c3-plat-side" points="{pts((left, base), (left + run, base + half), (left + run, base + half + thick), (left, base + thick))}"/>',
        f'<polygon class="c3-plat-side" points="{pts((left + run, base + half), (right - run, base + half), (right - run, base + half + thick), (left + run, base + half + thick))}"/>',
        f'<polygon class="c3-plat-side dark" points="{pts((right - run, base + half), (right, base), (right, base + thick), (right - run, base + half + thick))}"/>',
        f'<polygon class="c3-plat" points="{pts((left, base), (left + run, base - half), (right - run, base - half), (right, base), (right - run, base + half), (left + run, base + half))}"/>',
    ]
    for i, step in enumerate(steps):
        x = pad + i * (w + gap)
        on = step in marks
        height = 40 if on else 12
        top = base - height
        state = "on" if on else "off"
        if i < len(steps) - 1:              # flow to the next step, drawn on the platform
            ax = x + w + 3
            out.append(f'<path class="c3-flow" d="M{ax:.1f},{base} h{gap - 10}"/>'
                       f'<polygon class="c3-flow-head" points="{pts((ax + gap - 10, base - 3.5), (ax + gap - 5, base), (ax + gap - 10, base + 3.5))}"/>')
        out.append(f'<ellipse class="c3-shadow" cx="{x + hw + 7:.1f}" cy="{base + 5}" rx="{hw * 0.95:.1f}" ry="{d * 0.85:.1f}"/>')
        out.append(f'<polygon class="c3-left {state}" points="{pts((x, top), (x + hw, top + d), (x + hw, base + d), (x, base))}"/>')
        out.append(f'<polygon class="c3-right {state}" points="{pts((x + hw, top + d), (x + w, top), (x + w, base), (x + hw, base + d))}"/>')
        out.append(f'<polygon class="c3-top {state}" points="{pts((x, top), (x + hw, top - d), (x + w, top), (x + hw, top + d))}"/>')
        out.append(f'<text class="c3-num {state}" x="{x + hw}" y="{top + 4}" text-anchor="middle">{i + 1}</text>')
        pills = [f"{letter} · " + " ".join(f"H{n}" for n in sorted(nums)) for letter, nums in sorted(marks.get(step, {}).items())][:3]
        if pills:
            out.append(f'<path class="c3-pin" d="M{x + hw},{top - d - 1} V{top - d - 12}"/>')
        for j, text in enumerate(pills):
            py = top - d - 21 - j * 20
            pw = 16 + 6.3 * len(text)
            out.append(f'<rect class="c3-pill" x="{x + hw - pw / 2:.1f}" y="{py - 9}" width="{pw:.1f}" height="18" rx="9"/>'
                       f'<text class="c3-pill-t" x="{x + hw}" y="{py + 4}" text-anchor="middle">{_e(text)}</text>')
        ly = base + half + thick + 20
        label = _wrap(step, 14)
        for j, line in enumerate(label):
            out.append(f'<text class="c3-label {state}" x="{x + hw}" y="{ly + j * 13}" text-anchor="middle">{_e(line)}</text>')
        cy = ly + len(label) * 13 + 5
        names = companies.get(step) or []
        for j, name in enumerate(names[:3]):
            out.append(f'<text class="c3-co" x="{x + hw}" y="{cy + j * 12}" text-anchor="middle">{_e(_clip(name, 16))}</text>')
        if not names:
            out.append(f'<text class="c3-co none" x="{x + hw}" y="{cy}" text-anchor="middle">not tracked yet</text>')
    height = base + half + thick + 20 + 3 * 13 + 5 + 3 * 12 + 4
    from .profile_store import SECTORS

    gloss = next((x.get("gloss") for x in SECTORS if x.get("id") == theme), "")
    stage = next((summary.get("stage") for _, summary, _ in packs if summary.get("stage")), None)
    legend = "".join(f'<li><b>{_e(letter)}</b>{_e(summary.get("title"))}</li>' for letter, summary, _ in packs)
    name = SHORT_THEMES.get(theme, _theme_label(theme))
    return (f'<section class="card chain3d"><p class="eyebrow">The {_e(name)} supply chain · where the theses sit</p>'
            + (f'<p class="c3-gloss">{_e(gloss)}</p>' if gloss else "")
            + (f'<p class="muted small">Part of AI compute, in the {_e(stage.replace("_", " "))} layer. '
               f'<a href="{AI_COMPUTE_MAP}">See the AI compute map on equitylayer.io →</a></p>' if stage else "")
            + f'<div class="c3-wrap"><svg viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="The {_e(name)} supply chain, the companies tracked at each step, and the hypotheses that track them">'
            f'{"".join(out)}</svg></div><ul class="c3-legend">{legend}</ul>'
            '<p class="muted small">Materials on the left, data-center systems on the right. Green steps are tracked by '
            'a hypothesis.</p></section>')


def render(profile: dict | None, theses: list[dict], watchlists: list[dict], now: datetime | None = None,
           preview: dict | None = None, saved_at: str = "", packs: list[dict] | None = None,
           followed: dict[str, dict] | None = None, packs_as_of: str | None = None) -> str:
    followed = followed or {}
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
    for record in followed.values():
        pending = record.get("pending_review") if isinstance(record.get("pending_review"), dict) else None
        if record.get("unavailable_since"):
            title = (record.get("pack") or {}).get("title") or record.get("target_id")
            needs.append(f'<li>EquityLayer Research Pack <b>{_e(title)}</b>: not published since '
                         f'{_e(record.get("unavailable_since"))}, so it is not EquityLayer\'s current view. Its readings '
                         f'stay tracked. Remove it with <code>/el remove {_e(record.get("follow_id"))}</code> if you no '
                         'longer want it.</li>')
        elif pending:
            title = (record.get("pack") or {}).get("title") or record.get("target_id")
            what = ("a new revision to review; it moves to it only when you say so" if pending.get("revision_changed")
                    else "new data in a reading it watches; tell Hermes you've read it")
            needs.append(f'<li>EquityLayer Research Pack <b>{_e(title)}</b>: {what}.</li>')
    for record in watchlists:
        if isinstance(record.get("pending"), dict):
            new = ((record.get("last_check") or {}).get("new_count") or 0)
            owner = next((f for f in followed.values() if f.get("follow_id") == record.get("follow_id")
                          and isinstance(f.get("pack"), dict)), None) if record.get("follow_id") else None
            name = (owner or {}).get("pack", {}).get("title") if owner else record.get("title")
            needs.append(f'<li><b>{_e(name)}</b>: {_e(new)} new reading{"" if new == 1 else "s"} to read. '
                         'Tell Hermes "I\'ve read it" when you have.</li>')
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
    empty = not theses and not watchlists and not preview and not followed
    body = [
        f'<header><div class="brand"><svg width="26" height="26" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="3" fill="#173f32"/><circle cx="27.5" cy="10.5" r="4.25" fill="#c49a50"/><rect x="8.5" y="12.5" width="21" height="5.25" fill="#f8f5eb"/><rect x="8.5" y="20.25" width="15" height="5.25" fill="#f8f5eb"/><rect x="8.5" y="28" width="21" height="5.25" fill="#f8f5eb"/></svg>EquityLayer</div>'
        f'<h1>Your research</h1><p class="muted">Updated {_e(stamp)}'
        + (f" · {_e(about)}" if about else "") + "</p></header>",
    ]
    if empty:
        body.append('<section class="card"><p>Nothing tracked yet. In Hermes, type <code>/equitylayer:start</code>.</p></section>')
    live_block = ""
    if preview:
        card = _watch_card({"title": preview.get("title"), "pending": None,
                            "last_check": {"as_of": preview.get("as_of"), "rows": preview.get("rows") or [],
                                           "new_count": None, "next_due": "after you save"}})
        card = re.sub(r'<span class="tag[^"]*">[^<]*</span>', '<span class="tag">preview, not saved</span>', card, count=1)
        open_packs = [p for p in packs or [] if isinstance(p, dict) and p.get("kind") == "pack"
                      and p.get("theme_id") == preview.get("theme") and p.get("status") == "verified"
                      and p.get("access") == "public" and _pack_id(p.get("id")) and p.get("id") not in followed]
        pack = open_packs[0] if open_packs else None
        thesis_packs = [p for p in open_packs if p.get("category") == "thesis"]
        if thesis_packs:  # with categories, the recommendation is EquityLayer's thesis Packs
            follow_label = ("Follow EquityLayer's thesis Pack" if len(thesis_packs) == 1
                            else f"Follow EquityLayer's thesis Packs ({len(thesis_packs)})")
            follow_send = "I'd like to follow EquityLayer's thesis Packs. Show me their card first."
        else:
            follow_label = ("Follow EquityLayer's Research Pack" if len(open_packs) == 1
                            else f"Follow EquityLayer's Research Packs ({len(open_packs)})")
            follow_send = ("I'd like to follow EquityLayer's Research Pack. Show me its card first." if len(open_packs) == 1
                           else "I'd like to follow EquityLayer's Research Packs. Show me their card first.")
        readings_class = ' class="ghost"' if pack else ""
        actions = ('<div class="actions">'
                   + (f'<button type="button" data-hermes-send="{_e(follow_send)}">{_e(follow_label)}</button>'
                      if pack else "")
                   + f'<button type="button"{readings_class} data-hermes-send="I\'d like to follow these curated readings. Show me the card first.">'
                   'Follow these readings</button>'
                   '<button type="button" class="ghost" data-hermes-send="I have my own view.">I have my own view</button>'
                   '</div>')
        live_block = '<h2 id="live">Live now</h2>' + card + actions
        for row in preview.get("rows") or []:
            sources += [a for a in row.get("attribution") or [] if a not in sources]
    groups: dict[str, dict[str, list]] = {}
    for record in watchlists:
        groups.setdefault(_theme_of(record), {"watch": [], "theses": []})["watch"].append(record)
    for record in theses:
        groups.setdefault(_theme_of(record), {"watch": [], "theses": []})["theses"].append(record)
    unpublished = {pid for pid, r in followed.items() if r.get("unavailable_since")}
    # Keep the registry's order (EquityLayer lists its thesis Packs first), not the order of the local files.
    rank = {p.get("id"): n for n, p in enumerate(packs or []) if isinstance(p, dict)}
    hero_records = sorted(((pid, r) for pid, r in followed.items()
                           if isinstance(r.get("pack"), dict) and pid not in unpublished),
                          key=lambda item: rank.get(item[0], len(rank)))[:4]
    several = len(hero_records) > 1
    watch_by_id = {w.get("id"): w for w in watchlists}
    letters: dict[str, str] = {}
    for pid, r in hero_records:
        theme = (r.get("pack") or {}).get("theme_id")
        letters[pid] = chr(65 + sum(1 for q in letters if (followed[q].get("pack") or {}).get("theme_id") == theme))
    pack_heroes = {pid: _pack_hero(r, compact=several, open_=n == 0, readings=watch_by_id.get(r.get("readings_id")),
                                   letter=letters.get(pid))
                   for n, (pid, r) in enumerate(hero_records)}
    hero_follows = {r.get("follow_id") for pid, r in hero_records}
    # A Pack's readings are summed up on its own card; only readings you follow on their own get a card here.
    own = [_thesis_hero(r) for r in theses[:3]] or [
        h for h in (_readings_hero(r) for r in [w for w in watchlists if w.get("follow_id") not in hero_follows][:2]) if h]
    heroes = list(pack_heroes.values()) + own
    # One picture per sector of where its followed theses sit in the chain.
    diagrams = []
    themes_seen: list[str] = []
    for pid, r in hero_records:
        theme = (r.get("pack") or {}).get("theme_id")
        if theme and theme not in themes_seen:
            themes_seen.append(theme)
    for theme in themes_seen:
        group = [(chr(65 + n), r["pack"], [row for row in ((watch_by_id.get(r.get("readings_id")) or {}).get("last_check") or {}).get("rows") or []
                                           if isinstance(row, dict)])
                 for n, (pid, r) in enumerate([(pid, r) for pid, r in hero_records if (r.get("pack") or {}).get("theme_id") == theme])]
        diagrams.append(_chain_3d(theme, group))
    if heroes:
        body.append('<h2 id="glance">At a glance</h2>' + "".join(d for d in diagrams if d) + "".join(heroes))
    pack_themes = [t for t in sorted({_theme_of(r) for r in watchlists + theses}, key=_theme_order) if t != "other"]
    if preview and preview.get("theme") and preview["theme"] not in pack_themes:
        pack_themes.insert(0, preview["theme"])
    cards = _pack_cards(pack_themes[:3], packs, followed, packs_as_of, skip=set(pack_heroes) | unpublished)
    if cards and not heroes:  # before anything is followed, EquityLayer's theses lead and the readings follow
        body.append('<h2 id="theses">EquityLayer\'s research for this sector</h2>')
    body += cards
    # Theses first (followed ones above, published ones next), then the live readings behind them.
    if live_block:
        body.append(live_block)
    if needs:
        body.append(f'<section class="card needs" id="needs"><h2>Needs you</h2><ul>{"".join(needs)}</ul></section>')
    if groups:
        body.append('<h2 class="section" id="evidence">Evidence</h2><p class="muted small">The readings behind it, by sector and '
                    'supply-chain step.</p>')
    # Themes in the main column, one section per sector (the earlier local-workspace layout).
    for theme in sorted(groups, key=_theme_order):
        group = groups[theme]
        body.append(f'<h3 class="theme-h" id="theme-{_e(theme)}">{_e(_theme_label(theme))}</h3>'
                    + "".join(_watch_card(r) for r in group["watch"])
                    + "".join(_thesis_card(r) for r in group["theses"]))
    if event_items:
        body.append(f'<section class="card" id="events"><h2>Recent events</h2><ul>{event_items}</ul></section>')
    if up_items:
        body.append(f'<section class="card"><h2>Coming up</h2><ul>{up_items}</ul></section>')
    if sources:
        body.append('<section class="card"><h2>Sources</h2><ul class="small">'
                    + "".join(f"<li>{_e(s)}</li>" for s in sources[:12]) + "</ul></section>")
    body.append(f'<p class="muted small">Saved on this machine at <code>{_e(saved_at)}</code>. Reopen it any time with '
                '<code>/el dashboard</code>, from Artifacts in Hermes Desktop, or in any browser.</p>' if saved_at else "")
    body.append('<footer class="muted small">Generated on this machine from your local files. EquityLayer reports '
                "what moved and stops: nothing here says what to buy, sell, size or time. Not investment advice.</footer>")
    sidebar = _sidebar(groups, watchlists, preview, bool(needs))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>EquityLayer research</title>
<style>
:root{{--paper:#f4f2e9;--paper-bright:#fbfaf5;--ink:#15251e;--forest:#173f32;--forest-2:#245b46;--sage:#d7dfd2;--gold:#b18a46;
--line:#cfcec3;--muted:#667069;--warn:#9a5b1c;--seen:#245b46;--against:#a3322a;--late:#9a5b1c;--nodata:#8a8f88;
--display:"Instrument Serif","Iowan Old Style","Palatino Linotype",Georgia,serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
--body:Inter,-apple-system,"Segoe UI",system-ui,sans-serif}}
@media (prefers-color-scheme:dark){{:root{{--paper:#121a16;--paper-bright:#18221d;--ink:#e9ece4;--forest:#9cc7ae;--forest-2:#8fbfa3;
--sage:#24332b;--gold:#d2ab66;--line:#2f3d35;--muted:#9aa49d;--warn:#e0a35e;--seen:#8fbfa3;--against:#f08a80;--late:#e0a35e;--nodata:#8d958f}}}}
*{{box-sizing:border-box}}.layout{{display:grid;grid-template-columns:210px minmax(0,1fr);gap:28px;max-width:1180px;margin:0 auto;padding:22px 16px 44px}}main{{max-width:none;margin:0;padding:0;min-width:0}}.side{{position:sticky;top:16px;align-self:start;border-right:1px solid var(--line);padding-right:14px}}.side nav{{display:flex;flex-direction:column;gap:2px;margin-bottom:14px}}.side a{{text-decoration:none;color:var(--ink);font-size:14px;padding:6px 8px;border-radius:8px}}.side a:hover{{background:var(--paper-bright)}}.side-label{{font:500 10px/1.2 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:14px 0 6px}}.side-sub{{font-size:12px;color:var(--muted);padding:0 8px 4px 18px;display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.row-more summary{{cursor:pointer;font-size:12px;color:var(--muted);margin-top:4px}}.txt{{min-width:220px;white-space:normal}}.pack-readings{{margin:10px 0 4px;font-size:14px}}.tc-head{{display:flex;align-items:center;gap:10px}}.tc-head .eyebrow{{margin:0}}.tc-link{{margin-left:auto;font-size:13px}}.tc-thesis{{margin:6px 0 10px;font-size:21px;line-height:1.3}}.tc-list{{list-style:none;margin:0;padding:0;display:grid;gap:8px}}.tc-item{{border-left:3px solid var(--forest-2);padding:4px 0 4px 10px}}.tc-row{{display:flex;gap:8px;align-items:baseline}}.tc-n{{font:600 11px var(--mono);color:var(--forest-2)}}.tc-claim{{font-weight:600;flex:1}}.tc-due{{font:11px var(--mono);color:var(--muted);white-space:nowrap}}.tc-chips{{display:flex;flex-wrap:wrap;gap:6px;margin:5px 0 2px}}.chip{{font-size:12.5px;border:1px solid var(--line);border-radius:99px;padding:2px 9px;background:var(--paper)}}.chg.up{{color:var(--seen)}}.chg.down{{color:var(--against)}}.tc-wrong{{font-size:12.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}.tc-next{{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin-top:12px;font-size:13px}}.tc-k{{font:500 10px/1.2 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}}.nx.late{{color:var(--late)}}.light{{width:9px;height:9px;border-radius:50%;display:inline-block;flex:none;background:var(--nodata)}}.light.up{{background:var(--seen)}}.light.down{{background:var(--against)}}.chip.up{{border-color:var(--seen)}}.chip.down{{border-color:var(--against)}}.kv{{display:grid;grid-template-columns:104px minmax(0,1fr);gap:10px;font-size:13px;line-height:1.45;margin-top:3px}}.kv .k{{font:500 10px/1.9 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}.kv.good .v{{color:var(--seen)}}.kv.quiet .v{{color:var(--muted)}}.kv.bad .v{{color:var(--against)}}.kv .v{{overflow:hidden;text-overflow:ellipsis}}.kv .tc-chips{{margin:0}}.kv.src .v a{{margin-right:10px;font-size:12.5px}}.tc-rest{{margin-top:8px}}.tc-rest>summary{{margin:0 0 6px}}.tc-item{{padding-bottom:2px}}.tc-item summary{{cursor:pointer;list-style:none}}.tc-item summary::-webkit-details-marker{{display:none}}.tc-item details[open] summary{{margin-bottom:4px}}.tc-item summary .tc-n::before{{content:'▸ ';color:var(--muted)}}.tc-item details[open] summary .tc-n::before{{content:'▾ '}}.tc-holds{{font-size:12.5px;color:var(--seen)}}.tc-why summary{{cursor:pointer;font-size:12px;color:var(--forest-2);margin:2px 0}}.tc-why ul{{margin:4px 0 2px;padding-left:16px;font-size:12.5px;color:var(--muted)}}.tc-cal{{font-size:12.5px}}.c3-wrap{{overflow-x:auto;margin:8px 0 2px}}.chain3d svg{{width:100%;min-width:700px;height:auto;display:block}}.c3-plat{{fill:color-mix(in srgb,var(--forest-2) 7%,var(--paper-bright));stroke:var(--line)}}.c3-plat-side{{fill:var(--line)}}.c3-plat-side.dark{{fill:color-mix(in srgb,var(--line) 78%,#000)}}.c3-shadow{{fill:#000;opacity:.09}}.c3-top.on{{fill:var(--forest-2)}}.c3-left.on{{fill:var(--forest)}}.c3-right.on{{fill:color-mix(in srgb,var(--forest) 78%,#000)}}.c3-top.off{{fill:var(--paper-bright);stroke:var(--line)}}.c3-left.off{{fill:color-mix(in srgb,var(--line) 70%,var(--paper-bright))}}.c3-right.off{{fill:var(--line)}}.c3-top.on,.c3-left.on,.c3-right.on{{stroke:color-mix(in srgb,var(--forest-2) 60%,#fff);stroke-width:.6}}.c3-num{{font:600 11px var(--mono)}}.c3-num.on{{fill:#fff}}.c3-num.off{{fill:var(--muted)}}.c3-flow{{stroke:var(--gold);stroke-width:1.6;fill:none}}.c3-flow-head{{fill:var(--gold)}}.c3-pin{{stroke:var(--gold);stroke-width:1.4}}.c3-pill{{fill:var(--gold)}}.c3-pill-t{{font:600 10.5px var(--mono);fill:#1b1b1b}}.c3-label{{font:500 11.5px var(--body);fill:var(--muted)}}.c3-label.on{{fill:var(--ink);font-weight:600}}.c3-label{{font:500 11px var(--body);fill:var(--muted)}}.c3-label.on{{fill:var(--ink);font-weight:600}}.c3-arrow{{font:14px var(--body);fill:var(--gold)}}.c3-co{{font:11px var(--body);fill:var(--forest-2)}}.c3-co.none{{fill:var(--muted);font-style:italic}}.c3-gloss{{margin:2px 0 0;font-size:14px}}.c3-mark{{fill:var(--gold)}}.c3-mark-t{{font:600 10.5px var(--mono);fill:#1b1b1b}}.c3-legend{{list-style:none;margin:4px 0 6px;padding:0;font-size:13.5px;display:grid;gap:2px}}.c3-legend b{{display:inline-block;min-width:20px;margin-right:6px;padding:0 6px;border-radius:9px;background:var(--gold);color:#1b1b1b;font:600 11px/18px var(--mono);text-align:center}}.tc-letter{{font:600 12px var(--mono);background:var(--forest-2);color:#fff;border-radius:6px;padding:1px 7px}}.side-co{{display:flex;justify-content:space-between;gap:6px;font-size:13px;padding:4px 8px}}.side-co small{{font:11px var(--mono);color:var(--muted)}}.side-foot{{font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:10px}}@media (max-width:760px){{.layout{{grid-template-columns:1fr;gap:6px}}.side{{position:static;border-right:0;border-bottom:1px solid var(--line);padding:0 0 8px}}.side nav{{flex-direction:row;flex-wrap:wrap;margin-bottom:6px}}.side-sub,.side-label,.side-foot,.side nav.cos{{display:none}}}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 var(--body)}}

.brand{{display:flex;align-items:center;gap:9px;font-weight:600;font-size:17px;margin-bottom:18px}}.brand svg{{flex:0 0 auto}}
.eyebrow{{font:500 11px/1.2 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--forest-2);margin:0 0 6px}}
h1{{font:400 40px/1.05 var(--display);letter-spacing:-.01em;margin:0 0 6px}}h2{{font:500 11px/1.2 var(--mono);letter-spacing:.14em;
text-transform:uppercase;color:var(--forest-2);margin:30px 0 10px}}h3{{font:400 24px/1.15 var(--display);margin:0}}
.card{{background:var(--paper-bright);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:10px 0;
box-shadow:0 14px 40px rgba(21,37,30,.06)}}.card h2{{margin-top:0}}
.card-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
.tag{{font:500 11px/1 var(--mono);letter-spacing:.06em;padding:5px 9px;border-radius:99px;border:1px solid var(--line);color:var(--muted)}}
.tag.warn{{color:var(--warn);border-color:var(--warn)}}
.muted{{color:var(--muted)}}.small{{font-size:13px}}.unit{{color:var(--muted);font-size:12px}}.caveat{{color:var(--muted);font-size:12px}}
.role{{font-size:13px;margin:2px 0;color:var(--forest)}}.hyp{{margin:8px 0;font-family:var(--display);font-size:19px}}
.tbl{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;margin-top:8px}}
th,td{{text-align:left;padding:9px 6px;border-top:1px solid var(--line);vertical-align:top}}
th{{font:500 11px/1.2 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
.num{{white-space:nowrap;font-variant-numeric:tabular-nums}}.dot{{color:var(--forest-2);margin-right:6px}}.spark{{color:var(--forest-2)}}
tr.grp td{{font:500 11px/1.2 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--forest-2);background:var(--paper);padding:7px 6px}}
.chain{{margin:12px 0 6px}}.steps{{display:flex;flex-wrap:wrap;align-items:stretch;gap:8px;margin-top:8px}}
.step{{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:150px;flex:1}}
.step-name{{font:500 11px/1.3 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--forest-2);margin-bottom:7px}}
.step-cos{{display:flex;flex-wrap:wrap;gap:5px}}.badge{{font-size:12px;padding:2px 8px;border-radius:6px;background:var(--paper-bright);
border:1px solid var(--line)}}.arrow{{align-self:center;color:var(--gold)}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}}.chip{{font-size:12px;padding:3px 9px;border-radius:99px;border:1px solid var(--line)}}
.s-seen{{color:var(--seen)}}.s-against{{color:var(--against)}}.s-late{{color:var(--late)}}.s-no_data,.s-not_due{{color:var(--nodata)}}
.actions{{display:flex;gap:8px 14px;flex-wrap:wrap;align-items:center;margin:12px 0 0}}.actions button{{font:600 14px/1 var(--body);padding:12px 16px;border-radius:8px;
border:1px solid var(--forest);background:var(--forest);color:#fbfaf5;cursor:pointer}}
.actions button.ghost{{background:transparent;color:var(--forest)}}
.sig{{font:500 10px/1 var(--mono);letter-spacing:.08em;text-transform:uppercase;color:var(--gold);border:1px solid var(--line);border-radius:4px;padding:2px 5px;margin-right:6px;vertical-align:1px}}.pack{{border-color:var(--forest-2)}}.hero h3{{font:500 24px/1.25 var(--display);margin:4px 0 8px}}.hero-text.pack-view{{font-size:18px;line-height:1.45;font-family:inherit}}.hyp{{margin:10px 0 6px;padding-left:20px}}.hyp li{{margin:8px 0;line-height:1.45}}.hyp .tag{{white-space:nowrap}}.go{{font-weight:600}}.hero{{border-color:var(--forest-2);padding:20px 22px}}.hero-text{{font:400 26px/1.25 var(--display);margin:4px 0 10px}}.verdict{{font:600 13px/1 var(--body);padding:6px 10px;border-radius:99px;border:1px solid currentColor}}.v-seen{{color:var(--seen)}}.v-against{{color:var(--against)}}.v-late,.v-warn{{color:var(--late)}}.v-no_data{{color:var(--nodata)}}.movers{{margin:4px 0 8px;padding-left:18px}}.theme-h{{font:500 11px/1.2 var(--mono);letter-spacing:.14em;text-transform:uppercase;color:var(--forest-2);margin:18px 0 8px}}h2.section{{margin-top:34px}}details.more summary{{cursor:pointer;font:500 11px/1.2 var(--mono);letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:10px 0 4px}}.alert{{color:var(--warn);margin:8px 0 0}}.needs{{border-color:var(--gold);background:color-mix(in srgb,var(--gold) 7%,var(--paper-bright))}}
a{{color:var(--forest-2)}}footer{{margin-top:28px}}
@media (max-width:640px){{th:nth-child(4),td:nth-child(4),th:nth-child(5),td:nth-child(5){{display:none}}.num{{white-space:normal}}
td:first-child{{min-width:9em}}.arrow{{display:none}}.step{{min-width:100%}}h1{{font-size:32px}}}}
</style></head><body><div class="layout">{sidebar}<main>
{"".join(body)}
</main></div></body></html>
"""


JSON_NAME = "dashboard.json"
ICS_NAME = "calendar.ics"


def calendar_events(theses: list[dict], watchlists: list[dict], followed: dict[str, dict] | None = None) -> list[dict]:
    """Dates that can change what you follow: data due for tracked variables, Pack checks, hypothesis tests."""
    events: dict[tuple, dict] = {}

    def add(day: Any, what: str, item: Any) -> None:
        day = str(day or "")[:10]
        if len(day) == 10 and day[4] == "-":
            events.setdefault((day, what), {"date": day, "what": what, "item_id": item})

    for w in watchlists:
        for row in ((w.get("last_check") or {}).get("rows") or []):
            if isinstance(row, dict):
                add(row.get("next_reading"), f"New data due: {row.get('name')}", w.get("id"))
    for pid, r in (followed or {}).items():
        summary = r.get("pack") if isinstance(r.get("pack"), dict) else {}
        title = summary.get("title") or pid
        add(r.get("next_check_at"), f"EquityLayer Pack check: {title}", r.get("follow_id"))
        for n, h in enumerate([h for h in summary.get("hypotheses") or [] if isinstance(h, dict)], 1):
            add(h.get("due"), f"Hypothesis H{n} is tested: {_short_claim(h.get('statement'), 80)}", r.get("follow_id"))
    for t in theses:
        add((t.get("last_check") or {}).get("next_due"), f"Your thesis check: {t.get('title')}", t.get("id"))
    return sorted(events.values(), key=lambda e: (e["date"], e["what"]))


def calendar_ics(events: list[dict]) -> str:
    """All-day events in iCalendar format, so any calendar app can subscribe."""
    def esc(text: Any) -> str:
        return str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", " ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//EquityLayer//Hermes plugin//EN", "X-WR-CALNAME:EquityLayer research dates"]
    for n, e in enumerate(events):
        day = e["date"].replace("-", "")
        lines += ["BEGIN:VEVENT", f"UID:el-{day}-{n}@equitylayer.io", f"DTSTAMP:{day}T000000Z", f"DTSTART;VALUE=DATE:{day}",
                  f"SUMMARY:{esc(e['what'])}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def write_text(root: Path, name: str, text: str) -> Path:
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
JSON_FORMAT = "equitylayer-hermes-dashboard/1"


def _reading(row: dict) -> dict:
    latest = row.get("latest") or {}
    return {"variable": row.get("variable"), "name": row.get("name"), "company": _company(row),
            "entity": row.get("entity"),
            "period": latest.get("period"), "value": latest.get("value"), "unit": row.get("unit"),
            "withheld": latest.get("withheld"), "change": row.get("change") or None,
            "next_reading": row.get("next_reading"), "caveat": row.get("caveat"), "source_url": row.get("source_url")}


def snapshot(theses: list[dict], watchlists: list[dict], followed: dict[str, dict] | None = None,
             packs: list[dict] | None = None, now: datetime | None = None) -> dict:
    """The dashboard as data, for agents: the same facts as the page, read from the same local files."""
    followed = followed or {}
    stamp = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).isoformat(timespec="seconds")
    rank = {p.get("id"): n for n, p in enumerate(packs or []) if isinstance(p, dict)}
    watch_by_id = {w.get("id"): w for w in watchlists}
    linked = set()
    out_packs = []
    for pid, record in sorted(followed.items(), key=lambda kv: rank.get(kv[0], len(rank))):
        summary = record.get("pack") if isinstance(record.get("pack"), dict) else {}
        watch = watch_by_id.get(record.get("readings_id")) or {}
        if watch:
            linked.add(watch.get("id"))
        rows = [r for r in ((watch.get("last_check") or {}).get("rows") or []) if isinstance(r, dict)]
        by_var = {r.get("variable"): r for r in rows}
        pending = record.get("pending_review") if isinstance(record.get("pending_review"), dict) else None
        status = ("not_published" if record.get("unavailable_since") else
                  ("revision_to_review" if pending and pending.get("revision_changed") else
                   ("new_data_to_read" if pending else "current")))
        out_packs.append({
            "item_id": record.get("follow_id"), "pack_id": pid, "category": summary.get("category"),
            "theme_id": summary.get("theme_id"), "title": summary.get("title"), "view": summary.get("view"),
            "url": _https(summary.get("url")), "revision": summary.get("revision"), "status": status,
            "next_check": record.get("next_check_at") or record.get("fresh_until"),
            "hypotheses": [{
                "id": f"H{n}", "claim": _short_claim(h.get("statement")), "statement": h.get("statement"),
                "confidence": h.get("confidence"), "test_by": h.get("due"), "wrong_if": h.get("falsifier"),
                "if_it_holds": h.get("moves") or [],
                "role": h.get("role") or "core", "why_it_matters": h.get("angle"), "most_think": h.get("consensus"),
                "tracks": [_reading(by_var[v]) if v in by_var else {"variable": v} for v in h.get("variables") or []],
            } for n, h in enumerate([h for h in summary.get("hypotheses") or [] if isinstance(h, dict)], 1)],
            "readings_unread": isinstance(watch.get("pending"), dict),
        })
    own = []
    for record in theses:
        harness = record.get("harness") if isinstance(record.get("harness"), dict) else {}
        last = record.get("last_check") if isinstance(record.get("last_check"), dict) else {}
        own.append({"item_id": record.get("id"), "title": record.get("title"), "hypothesis": harness.get("hypothesis"),
                    "counts": last.get("counts"), "wrong_if_fired": last.get("wrong_if_fired") or [],
                    "needs_human": last.get("needs_human"), "next_check": last.get("next_due"),
                    "unread": isinstance(record.get("pending_baseline"), dict)})
    readings = [{"item_id": w.get("id"), "title": w.get("title"), "theme": w.get("theme"),
                 "unread": isinstance(w.get("pending"), dict),
                 "next_check": (w.get("last_check") or {}).get("next_due"),
                 "readings": [_reading(r) for r in ((w.get("last_check") or {}).get("rows") or []) if isinstance(r, dict)]}
                for w in watchlists if w.get("id") not in linked]
    return {"format": JSON_FORMAT, "generated_at": stamp, "equitylayer_packs": out_packs, "your_theses": own,
            "readings": readings, "calendar": calendar_events(theses, watchlists, followed),
            "note": "Built on this machine from local files. Research evidence, not a trade instruction. "
                    "Not investment advice."}


def write_json(root: Path, data: dict) -> Path:
    import json

    path = Path(root) / JSON_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


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
