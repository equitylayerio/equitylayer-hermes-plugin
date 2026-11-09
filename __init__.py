"""EquityLayer for Hermes Agent: track your own investment thesis against EquityLayer's variable catalog."""

from __future__ import annotations

from pathlib import Path

TOOLSET = "equitylayer"


def register(ctx) -> None:
    # Imported here so the package root has no relative imports at module load.
    from . import commands, schemas
    from .tools import EquityLayerTools

    service = EquityLayerTools(
        get_config=ctx.get_config,
        in_cron=lambda: ctx.current_cron_execution() is not None,
    )
    for schema, handler in (
        # Your own thesis (primary)
        (schemas.EL_PLAN_THESIS, service.el_plan_thesis),
        (schemas.EL_GET_VARIABLE, service.el_get_variable),
        (schemas.EL_HARNESS_SAVE, service.el_harness_save),
        (schemas.EL_HARNESS_CHECK, service.el_harness_check),
        (schemas.EL_HARNESS_SEEN, service.el_harness_seen),
        (schemas.EL_HARNESS_LIST, service.el_harness_list),
        # Published research (secondary)
        (schemas.EL_LIST_REGISTRY, service.el_list_registry),
        (schemas.EL_GET_PACK, service.el_get_pack),
        (schemas.EL_SCORECARD, service.el_scorecard),
        (schemas.EL_FOLLOW_CREATE, service.el_follow_create),
        (schemas.EL_FOLLOW_CHECK, service.el_follow_check),
        (schemas.EL_FOLLOW_LIST, service.el_follow_list),
    ):
        ctx.register_tool(name=schema["name"], toolset=TOOLSET, schema=schema, handler=handler, emoji="📈")

    ctx.register_command(
        "el",
        handler=commands.make_slash_handler(service),
        description="EquityLayer: track your own thesis (plan, check, seen) and published research",
        args_hint="<plan|var|theses|show|check|seen|remove|schedule|registry|pack|follow|follows>",
    )
    ctx.register_cli_command(
        name="equitylayer",
        help="EquityLayer research helpers",
        setup_fn=commands.setup_cli,
        handler_fn=commands.run_cli,
    )

    # Recall across chats: a pointer list rebuilt from the local harness files at each new session.
    from .memory_section import MAX_CHARS, SECTION_ID, make_section

    ctx.register_system_prompt_section(SECTION_ID, make_section(ctx.get_config), max_chars=MAX_CHARS)

    for child in sorted((Path(__file__).parent / "skills").iterdir()):
        if (child / "SKILL.md").exists():
            ctx.register_skill(child.name, child / "SKILL.md")

    commands.register_blueprints(ctx)
