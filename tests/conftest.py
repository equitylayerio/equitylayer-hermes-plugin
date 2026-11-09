"""Load the plugin under an importable name; the repo root is the package."""

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest
from support import fixture_text

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = "equitylayer_plugin"

if PACKAGE not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        PACKAGE, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)


class FakeMcp(httpx.MockTransport):
    """Replays recorded SSE by tool name and records every call."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        params = json.loads(request.content)["params"]
        self.calls.append((params["name"], params["arguments"]))
        route = self.routes[params["name"]]
        if isinstance(route, int):
            return httpx.Response(route)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=fixture_text(route))

    def names(self) -> list:
        return [name for name, _ in self.calls]


@pytest.fixture
def make_service(tmp_path):
    from equitylayer_plugin.follows import FollowStore
    from equitylayer_plugin.tools import EquityLayerTools

    store = FollowStore(tmp_path)

    def build(routes=None, config=None, in_cron=False):
        settings = config or {}
        transport = FakeMcp(routes or {})
        service = EquityLayerTools(
            get_config=lambda key, default=None: settings.get(key, default),
            in_cron=lambda: in_cron,
            store_factory=lambda: store,
            transport=transport,
        )
        return service, transport, store

    return build
