"""The /el slash command, the `hermes equitylayer` CLI, and the scheduling blueprint."""

from __future__ import annotations

import shlex
from typing import Any

from .tools import EquityLayerTools

SKILL_REF = "equitylayer:equitylayer-research"
CRON_NAME = "EquityLayer follow check"
CRON_PROMPT = (
    "Call el_follow_check with no arguments to check local EquityLayer Follow Cards that are due. "
    "If no result needs review and none failed, respond with only [SILENT]. Otherwise summarize each "
    "update using only figures and sources from the tool result, and tell the user to review it and run "
    "/el check <follow_id> --accept. Never set accept_next. Never pay or authenticate. "
    "This is research evidence, not investment advice."
)

HELP = """**EquityLayer commands**

- `/el registry [publisher]`: list the Research Registry
- `/el pack <pack_id> [symbol ...]`: open a research pack
- `/el scorecard <id>`: show a research-quality scorecard
- `/el test <view_id>`: test a public view and save its baseline
- `/el update <view_id>`: check a view against the saved baseline
- `/el follow <id>`: follow a registry entry on this machine
- `/el follows`: list local follows
- `/el check [follow_id] [--accept]`: check one follow, or every due follow
- `/el unfollow <follow_id>`: remove a local follow
- `/el schedule`: show how to schedule follow checks

Research evidence, not investment advice."""


def _render(result: dict) -> str:
    if result.get("ok"):
        return result.get("markdown") or "Done."
    parts = [f"**EquityLayer:** {result.get('error', 'error')}"]
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


def schedule_text(time_of_day: str = "09:00", timezone: str = "Asia/Taipei") -> str:
    hour, _, minute = time_of_day.partition(":")
    create = (
        f"hermes cron create {shlex.quote(f'{int(minute or 0)} {int(hour)} * * *')} "
        f"{shlex.quote(CRON_PROMPT)} --skill {SKILL_REF} --name {shlex.quote(CRON_NAME)} "
        f"--timezone {shlex.quote(timezone)}"
    )
    return (
        "**Schedule EquityLayer follow checks**\n\n"
        "In a Hermes session, fill in the blueprint:\n\n"
        "```text\n/blueprint equitylayer:follow-check\n```\n\n"
        "Or from a terminal:\n\n"
        f"```bash\n{create}\n```\n\n"
        "The job runs daily but only contacts EquityLayer for follows whose `next_check_at` has arrived. "
        "It stays silent when nothing changed, never accepts an update, and never pays."
    )


def make_slash_handler(service: EquityLayerTools):
    def handle(raw_args: str = "", **_session: Any) -> str:
        words = (raw_args or "").split()
        if not words or words[0] in ("help", "-h", "--help"):
            return HELP
        command, rest = words[0].lower(), words[1:]
        first = rest[0] if rest else ""
        if command == "registry":
            return _render(service.run(EquityLayerTools._registry, {"publisher": first}))
        if command == "pack":
            args = {"pack_id": first, "symbols": rest[1:]}
            return _render(service.run(EquityLayerTools._pack, args))
        if command == "scorecard":
            return _render(service.run(EquityLayerTools._scorecard, {"id": first}))
        if command == "test":
            return _render(service.run(EquityLayerTools._test_thesis, {"thesis_id": first}))
        if command == "update":
            return _render(service.run(EquityLayerTools._thesis_update, {"thesis_id": first}))
        if command == "follow":
            if not first:
                return "Usage: `/el follow <id>`. Run `/el registry` for ids."
            return _render(service.run(_follow_by_id, {"id": first}))
        if command == "follows":
            return _render(service.run(EquityLayerTools._follow_list, {}))
        if command == "check":
            accept = "--accept" in rest
            ids = [w for w in rest if w != "--accept"]
            args = {"follow_id": ids[0] if ids else "", "accept_next": accept}
            return _render(service.run(EquityLayerTools._follow_check, args))
        if command == "unfollow":
            return _render(service.run(EquityLayerTools._follow_remove, {"follow_id": first}))
        if command == "schedule":
            return schedule_text()
        return HELP

    return handle


def setup_cli(subparser: Any) -> None:
    subs = subparser.add_subparsers(dest="equitylayer_command")
    schedule = subs.add_parser("schedule", help="Print how to schedule follow checks")
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


def register_blueprint(ctx: Any) -> None:
    ctx.register_automation_blueprint(
        "follow-check",
        title=CRON_NAME,
        description="Every day, check local EquityLayer Follow Cards that are due and report only real updates.",
        category="research",
        schedule_template="{minute} {hour} * * *",
        prompt_template=CRON_PROMPT,
        slots=[
            {"name": "time", "type": "time", "label": "What time?", "default": "09:00"},
            {"name": "deliver", "type": "enum", "label": "Where to deliver?", "default": "origin",
             "options": ["origin", "local"], "strict": False},
        ],
        skills=[SKILL_REF],
        tags=["research", "finance"],
    )
