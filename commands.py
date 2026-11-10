"""The /el slash command, the `hermes equitylayer` CLI, and the scheduling blueprints."""

from __future__ import annotations

import shlex
from typing import Any

from .tools import EquityLayerTools

HARNESS_SKILL = "equitylayer:equitylayer-thesis-harness"
RESEARCH_SKILL = "equitylayer:equitylayer-research"

THESIS_CRON_NAME = "EquityLayer daily check"
THESIS_CRON_PROMPT = (
    "Call el_harness_check with no arguments, then el_watch_check with no arguments, to check the user's saved "
    "EquityLayer theses and watchlists that are due. If report_total is 0 in both, respond with only [SILENT]. "
    "Otherwise show each markdown as returned, keeping every needs-you item, status, new reading, event, caveat and "
    "source. Then stop: do not add an interpretation, do not change anything, and never call el_harness_seen or "
    "el_watch_seen. Never say what to buy, sell, size or time. End with: say \"I've read it\" once you have read it."
)
FOLLOW_CRON_NAME = "EquityLayer follow check"
FOLLOW_CRON_PROMPT = (
    "Call el_follow_check with no arguments to check local EquityLayer Follow Cards that are due. "
    "If no result needs review and none failed, respond with only [SILENT]. Otherwise summarize each "
    "update using only figures and sources from the tool result, and tell the user to review it and run "
    "/el follow-check <follow_id> --accept. Never set accept_next. Never pay or authenticate. "
    "This is research evidence, not investment advice."
)

START_TEXT = """**Start researching with EquityLayer**

Type `/equitylayer:start`, or say "Help me start researching with EquityLayer". Four decisions: sector (CPO, space, custom AI chips or your own), how to follow it (curated readings, or your own view), one card to approve, and how often to check. Hermes shows live readings before asking you for anything, saves on this machine, sets up the daily check in that chat, and keeps a local dashboard (`/el dashboard`).

It never says what to buy, sell, size or time."""

HELP = """**EquityLayer: track your own thesis**

- `/equitylayer:start`: guided setup, one question at a time (start here)
- `/el profile`: your saved research profile (sectors, check time, language)
- `/el dashboard`: write the local dashboard and show where it is
- `/el watches` · `/el watch-check [id]` · `/el watch-seen <id>` · `/el unwatch <id>`: curated readings you follow
- `/el plan [--theme optical_cpo] [--company 3363.TWO] <your thesis>`: find catalog variables that could track it (nothing is stored)
- `/el var <variable id>`: read a variable's unit, caveat and recent readings
- `/el theses`: list the harnesses saved on this machine
- `/el show <id>`: show a harness's four parts
- `/el check [id]`: check one harness now, or every harness that is due
- `/el seen <id>`: mark the last check as read, so it becomes your baseline
- `/el remove <id>`: delete a harness from this machine
- `/el schedule [HH:MM] [Area/City]`: check due harnesses every day

**Published research (secondary)**

- `/el registry`: list current Research Packs (may be empty)
- `/el pack <pack_id>` · `/el scorecard <id>` · `/el follow <id>` · `/el follows` · `/el follow-check [id] [--accept]` · `/el unfollow <id>`

EquityLayer reports what moved and stops. You own the judgment. Not investment advice."""


def _render(result: dict) -> str:
    if result.get("ok"):
        return result.get("markdown") or "Done."
    parts = [f"**EquityLayer:** {result.get('error', 'error')}"]
    problems = result.get("problems")
    if isinstance(problems, list) and problems:
        parts.append("\n".join(f"- {p}" for p in problems))
    parts += [str(result[k]) for k in ("message", "hint", "pricing_url") if result.get(k)]
    return "\n\n".join(parts)


def _follow_by_id(service: EquityLayerTools, args: dict) -> dict:
    """Use the follow arguments exactly as the registry publishes them for this id."""
    entry_id = args["id"]
    registry = service._registry({})
    if not registry.get("ok"):
        return registry
    for entry in registry["entries"]:
        follow = entry.get("follow")
        if entry.get("id") == entry_id and isinstance(follow, dict):
            return service._follow_create(follow.get("arguments") or {})
    return {
        "ok": False,
        "error": "unknown_registry_entry",
        "message": f"`{entry_id}` is not a followable registry entry. Run `/el registry`.",
    }


def _plan_args(words: list[str]) -> dict:
    """`/el plan [--theme ID] [--company X]... <thesis>`: flags first, the rest is the thesis."""
    args: dict = {"entities": []}
    rest = list(words)
    while len(rest) >= 2 and rest[0] in ("--theme", "--company"):
        flag, value = rest.pop(0), rest.pop(0)
        if flag == "--theme":
            args["theme_id"] = value
        else:
            args["entities"].append(value)
    args["thesis_text"] = " ".join(rest)
    return args


def _watch_check_as_person(service: EquityLayerTools, args: dict) -> dict:
    return service._watch_check(args, seen=True)


def _check_as_person(service: EquityLayerTools, args: dict) -> dict:
    # A slash command's output goes straight to the person, so the check counts as read.
    return service._harness_check(args, seen=True)


def _cron_command(schedule: str, prompt: str, skill: str, name: str, timezone: str) -> str:
    return (
        f"hermes cron create {shlex.quote(schedule)} {shlex.quote(prompt)} --skill {skill} "
        f"--name {shlex.quote(name)} --timezone {shlex.quote(timezone)}"
    )


def schedule_text(time_of_day: str = "09:00", timezone: str = "Asia/Taipei") -> str:
    hour, _, minute = time_of_day.partition(":")
    hour_n, minute_n = int(hour), int(minute or 0)
    if not (0 <= hour_n <= 23 and 0 <= minute_n <= 59):
        raise ValueError(time_of_day)
    schedule = f"{minute_n} {hour_n} * * *"
    thesis = _cron_command(schedule, THESIS_CRON_PROMPT, HARNESS_SKILL, THESIS_CRON_NAME, timezone)
    follow = _cron_command(schedule, FOLLOW_CRON_PROMPT, RESEARCH_SKILL, FOLLOW_CRON_NAME, timezone)
    return (
        "**Schedule EquityLayer thesis checks**\n\n"
        "In a Hermes session, fill in the blueprint:\n\n"
        "```text\n/blueprint equitylayer:thesis-check\n```\n\n"
        "Or from a terminal:\n\n"
        f"```bash\n{thesis}\n```\n\n"
        "The job runs daily but only contacts EquityLayer for harnesses whose next due date has arrived. It stays "
        "silent when nothing moved and nothing needs you, never marks a check as read, never edits your harness, "
        "and never pays.\n\n"
        "For followed Research Packs (when one is published): `/blueprint equitylayer:follow-check`, or\n\n"
        f"```bash\n{follow}\n```"
    )


def _schedule_args(rest: list[str]) -> str:
    time_of_day = next((w for w in rest if ":" in w), "09:00")
    timezone = next((w for w in rest if "/" in w), "Asia/Taipei")
    try:
        return schedule_text(time_of_day, timezone)
    except ValueError:
        return "Usage: `/el schedule [HH:MM] [Area/City]`, for example `/el schedule 08:30 Asia/Taipei`."


def make_slash_handler(service: EquityLayerTools):
    def handle(raw_args: str = "", **_session: Any) -> str:
        text = (raw_args or "").strip()
        words = text.split()
        if not words or words[0] in ("help", "-h", "--help"):
            return HELP
        command, rest = words[0].lower(), words[1:]
        first = rest[0] if rest else ""
        run = service.run

        # Your own thesis
        if command in ("start", "setup", "onboard"):
            return START_TEXT
        if command == "profile":
            return _render(run(EquityLayerTools._profile_get, {}))
        if command == "dashboard":
            return _render(run(EquityLayerTools._dashboard, {}))
        if command in ("watches", "watchlists"):
            return _render(run(EquityLayerTools._watch_list, {"watch_id": first}))
        if command == "watch-check":
            return _render(run(_watch_check_as_person, {"watch_id": first}))
        if command == "watch-seen":
            return _render(run(EquityLayerTools._watch_seen, {"watch_id": first}))
        if command == "unwatch":
            return _render(run(EquityLayerTools._watch_remove, {"watch_id": first}))
        if command == "plan":
            args = _plan_args(rest)
            if not args.get("thesis_text"):
                return "Usage: `/el plan [--theme optical_cpo] <your thesis in a sentence or two>`."
            return _render(run(EquityLayerTools._plan, args))
        if command in ("var", "variable"):
            return _render(run(EquityLayerTools._variable, {"variable": first}))
        if command in ("theses", "harnesses", "list"):
            return _render(run(EquityLayerTools._harness_list, {}))
        if command == "show":
            if not first:
                return "Usage: `/el show <id>`. Run `/el theses` for ids."
            return _render(run(EquityLayerTools._harness_list, {"harness_id": first}))
        if command == "check":
            return _render(run(_check_as_person, {"harness_id": first}))
        if command == "seen":
            return _render(run(EquityLayerTools._harness_seen, {"harness_id": first}))
        if command in ("remove", "delete"):
            return _render(run(EquityLayerTools._harness_remove, {"harness_id": first}))
        if command == "schedule":
            return _schedule_args(rest)

        # Published research
        if command == "registry":
            return _render(run(EquityLayerTools._registry, {"publisher": first}))
        if command == "pack":
            return _render(run(EquityLayerTools._pack, {"pack_id": first, "symbols": rest[1:]}))
        if command == "scorecard":
            return _render(run(EquityLayerTools._scorecard, {"id": first}))
        if command == "follow":
            if not first:
                return "Usage: `/el follow <id>`. Run `/el registry` for ids."
            return _render(run(_follow_by_id, {"id": first}))
        if command == "follows":
            return _render(run(EquityLayerTools._follow_list, {}))
        if command == "follow-check":
            accept = "--accept" in rest
            ids = [w for w in rest if w != "--accept"]
            return _render(run(EquityLayerTools._follow_check,
                               {"follow_id": ids[0] if ids else "", "accept_next": accept}))
        if command == "unfollow":
            return _render(run(EquityLayerTools._follow_remove, {"follow_id": first}))
        return HELP

    return handle


def setup_cli(subparser: Any) -> None:
    subs = subparser.add_subparsers(dest="equitylayer_command")
    schedule = subs.add_parser("schedule", help="Print how to schedule thesis checks")
    schedule.add_argument("--time", default="09:00", help="Daily check time as HH:MM (default 09:00)")
    schedule.add_argument("--timezone", default="Asia/Taipei", help="IANA timezone (default Asia/Taipei)")
    subparser.set_defaults(func=run_cli)


def run_cli(args: Any) -> None:
    if getattr(args, "equitylayer_command", None) == "schedule":
        try:
            print(schedule_text(args.time, args.timezone))
        except ValueError:
            print("--time must look like 09:00")
        return
    print("Usage: hermes equitylayer schedule [--time HH:MM] [--timezone ZONE]")


def register_blueprints(ctx: Any) -> None:
    slots = [
        {"name": "time", "type": "time", "label": "What time?", "default": "09:00"},
        {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
         "options": ["origin", "local"], "strict": False},
    ]
    ctx.register_automation_blueprint(
        "thesis-check",
        title=THESIS_CRON_NAME,
        description="Every day, check your saved watchlists and theses that are due. Silent unless something is new or needs you.",
        category="research",
        schedule_template="{minute} {hour} * * *",
        prompt_template=THESIS_CRON_PROMPT,
        slots=slots,
        skills=[HARNESS_SKILL],
        tags=["research", "finance", "thesis"],
    )
    ctx.register_automation_blueprint(
        "follow-check",
        title=FOLLOW_CRON_NAME,
        description="Every day, check local EquityLayer Follow Cards that are due and report only real updates.",
        category="research",
        schedule_template="{minute} {hour} * * *",
        prompt_template=FOLLOW_CRON_PROMPT,
        slots=slots,
        skills=[RESEARCH_SKILL],
        tags=["research", "finance"],
    )
