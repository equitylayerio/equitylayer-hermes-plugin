"""Optional live checks: `pytest -m network`. Public free tools only."""

import pytest

from equitylayer_plugin.follows import FollowStore
from equitylayer_plugin.mcp_client import McpClient
from equitylayer_plugin.tools import EquityLayerTools

pytestmark = pytest.mark.network


def test_registry_and_public_pack():
    client = McpClient()
    assert client.call_tool("list_registry")["entries"]
    assert client.call_tool("get_research_pack", {"pack_id": "tw-monthly-revenue"})["records"]


def test_follow_create_check_list_on_the_local_store(tmp_path):
    service = EquityLayerTools(store_factory=lambda: FollowStore(tmp_path))
    created = service._follow_create({"pack_id": "tw-monthly-revenue"})
    assert created["ok"], created
    checked = service._follow_check({"follow_id": created["follow_id"]})
    assert checked["ok"] and checked["errors"] == 0, checked
    assert service._follow_list({})["count"] == 1
