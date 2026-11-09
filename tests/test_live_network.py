"""Optional live checks: `pytest -m network`. Set EQUITYLAYER_TEST_MCP_URL to test a local server."""

import os

import pytest

from equitylayer_plugin.harness_store import HarnessStore
from equitylayer_plugin.follows import FollowStore
from equitylayer_plugin.mcp_client import DEFAULT_MCP_URL, McpClient
from equitylayer_plugin.tools import EquityLayerTools

pytestmark = pytest.mark.network
URL = os.environ.get("EQUITYLAYER_TEST_MCP_URL", DEFAULT_MCP_URL)
THESIS = (
    "Co-packaged optics moves from pilot to volume in AI switches by late 2027, so optical component "
    "suppliers see revenue rise before switch makers do."
)


def _service(tmp_path):
    return EquityLayerTools(
        get_config=lambda key, default=None: URL if key == "mcp_url" else default,
        store_factory=lambda: FollowStore(tmp_path),
        harness_store_factory=lambda: HarnessStore(tmp_path),
    )


def test_registry_answers_even_when_empty():
    assert isinstance(McpClient(URL).call_tool("list_registry").get("entries"), list)


def test_plan_save_check_seen_loop(tmp_path):
    from support import FIXTURES  # noqa: F401 - keeps tests importable from the repo root
    import json
    from pathlib import Path

    service = _service(tmp_path)
    plan = service._plan({"thesis_text": THESIS, "theme_id": "optical_cpo"})
    assert plan["ok"] and plan["candidates"], plan
    harness = json.loads((Path(__file__).parent / "harness_demo.json").read_text())["harness"]
    saved = service._harness_save({"harness": harness})
    assert saved["ok"] and saved["validated"], saved
    checked = service._harness_check({"harness_id": saved["harness_id"]})
    assert checked["ok"] and checked["errors"] == 0, checked
    assert service._harness_seen({"harness_id": saved["harness_id"]})["ok"]
