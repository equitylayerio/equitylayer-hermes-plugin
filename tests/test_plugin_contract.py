"""The manifest must match what register() actually registers (catalog rule 6)."""

from pathlib import Path

import yaml

import equitylayer_plugin

ROOT = Path(__file__).resolve().parent.parent


class RecordingContext:
    def __init__(self):
        self.tools, self.commands, self.cli, self.skills, self.blueprints = [], [], [], [], []

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
    assert ctx.skills == ["equitylayer-research"]
    assert ctx.blueprints == ["follow-check"]


def test_manifest_defaults_and_no_required_env():
    manifest = _manifest()
    assert "requires_env" not in manifest
    assert manifest["config_schema"]["mcp_url"]["default"] == "https://equitylayer.io/mcp"
    assert manifest["config_schema"]["demo_mode"]["default"] is True
