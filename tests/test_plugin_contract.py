"""The manifest must match what register() actually registers (catalog rule 6)."""

from pathlib import Path

import yaml

import equitylayer_plugin

ROOT = Path(__file__).resolve().parent.parent


class RecordingContext:
    def __init__(self):
        self.tools, self.commands, self.cli, self.skills, self.blueprints = [], [], [], [], []
        self.sections = []

    def get_config(self, key, default=None):
        return default

    def current_cron_execution(self):
        return None

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        assert schema["name"] == name and toolset == "equitylayer" and callable(handler)
        self.tools.append(name)

    def register_command(self, name, handler, **kwargs):
        self.commands.append(name)

    def register_cli_command(self, name, **kwargs):
        self.cli.append(name)

    def register_skill(self, name, path):
        assert Path(path).exists()
        self.skills.append(name)

    def register_automation_blueprint(self, key, **kwargs):
        self.blueprints.append(key)

    def register_system_prompt_section(self, id, content, *, position="after_memory", max_chars=4000):
        assert callable(content) and position == "after_memory" and max_chars <= 4000
        self.sections.append(id)


def _registered():
    ctx = RecordingContext()
    equitylayer_plugin.register(ctx)
    return ctx


def _manifest():
    return yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))


def test_provides_tools_matches_register_exactly():
    assert sorted(_manifest()["provides_tools"]) == sorted(_registered().tools)


def test_other_surfaces_are_registered():
    ctx = _registered()
    assert ctx.commands == ["el"]
    assert ctx.cli == ["equitylayer"]
    assert ctx.skills == ["equitylayer-research", "equitylayer-thesis-harness", "start"]
    assert ctx.blueprints == ["daily-check"]
    assert ctx.sections == ["equitylayer.tracked-theses"]


def test_manifest_defaults_and_no_required_env():
    manifest = _manifest()
    assert "requires_env" not in manifest
    assert manifest["config_schema"]["mcp_url"]["default"] == "https://equitylayer.io/mcp"
    assert set(manifest["config_schema"]) == {"mcp_url", "recall_in_new_chats"}
    assert manifest["config_schema"]["recall_in_new_chats"]["default"] is True


def test_skills_never_tell_the_model_to_trade():
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        text = path.read_text(encoding="utf-8")
        assert "Never say what to buy, sell, size or time" in text, path


def test_start_skill_schedules_with_the_exact_cron_prompt():
    from equitylayer_plugin.commands import HARNESS_SKILL, THESIS_CRON_PROMPT

    text = (ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    assert THESIS_CRON_PROMPT in text
    assert HARNESS_SKILL in text
    assert "`deliver`: `origin`" in text
    assert "Do not run the job now." in text


def test_start_skill_offers_the_websites_sectors_in_order():
    from equitylayer_plugin.profile_store import SECTORS

    # Mirrors ONBOARDING_SECTORS in EquityLayer's lib/harness.ts (AC, 2026-11-10).
    assert [s["label"] for s in SECTORS] == [
        "CPO and optical networking", "Space infrastructure", "Custom AI chips (ASIC)", "Something else"]
    assert [s["id"] for s in SECTORS if s["recommended"]] == ["optical_cpo"]
    text = (ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    for phrase in ("One question per message", "(recommended)", "Never write a view for the person",
                   "el_profile", "Follow EquityLayer's Research Packs (recommended)",
                   "call `el_track` with each chosen `pack_id`, one call per Pack",
                   "1. Follow the curated readings (recommended)",
                   "On yes, call `el_track` with the title", "On yes, call `el_track` with the harness",
                   "el_dashboard_render", "call `el_track` with that `item_id` and the harness",
                   "Before decision 2, show what is live"):
        assert phrase in text


def test_start_skill_defaults_to_english_and_introduces_equitylayer_briefly():
    text = (ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    assert "**Use English** unless the person writes to you in another language" in text
    assert "or the device's language does not set it" in text
    assert "in at most three short sentences across the whole setup" in text
    assert "EquityLayer makes your agent better at equity research" in text
    assert "no superlatives" in text


def test_dashboard_preview_comes_with_the_live_readings():
    text = (ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    preview = text.index("Then call `el_dashboard_render` with `preview_variables`")
    assert text.index("Before decision 2, show what is live") < preview < text.index("## Decision 2.")
    first_check = text.index("**Then check once:**")
    assert first_check < text.index("Then call `el_dashboard_render` (no preview now)") < text.index("## Decision 4.")


def test_skills_name_only_registered_tools():
    import re

    registered = set(_manifest()["provides_tools"])
    for path in (ROOT / "skills").glob("*/SKILL.md"):
        named = set(re.findall(r"\bel_[a-z_]+", path.read_text(encoding="utf-8")))
        assert named <= registered, (path.name, named - registered)


def test_code_strings_name_only_registered_tools():
    """Text the model or person reads must not point at a tool that is no longer registered."""
    import ast
    import re

    registered = set(_manifest()["provides_tools"])
    found = {}
    for path in ROOT.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for name in re.findall(r"\bel_[a-z_]+", node.value):
                    if name not in registered:
                        found.setdefault(path.name, set()).add(name)
    assert not found, found


def test_help_lists_five_commands_and_old_ones_still_route(make_service):
    from equitylayer_plugin.commands import HELP, make_slash_handler

    assert all(cmd in HELP for cmd in ("/el start", "/el dashboard", "/el check", "/el seen", "/el list"))
    service, _, _ = make_service()
    handle = make_slash_handler(service)
    assert "You don't track anything yet" in handle("theses") and "You don't track anything yet" in handle("follows")
    assert "Usage: `/el remove <id>`" in handle("remove")


def test_start_skill_never_calls_an_in_review_pack_available():
    text = (ROOT / "skills" / "start" / "SKILL.md").read_text(encoding="utf-8")
    assert '"EquityLayer Pack in review, not published yet"' in text
    assert "An in-review Pack cannot be read or followed yet" in text
