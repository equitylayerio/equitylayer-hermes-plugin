import httpx
import pytest
from support import fixture_text

from equitylayer_plugin.mcp_client import (
    McpClient,
    McpError,
    extract_tool_payload,
    parse_rpc_response,
    validate_mcp_url,
)


def test_parses_recorded_sse_into_a_payload():
    message = parse_rpc_response("text/event-stream", fixture_text("list_registry"), 1)
    payload = extract_tool_payload(message["result"])
    assert payload["registry"] == "EquityLayer Research Registry"
    assert {e["id"] for e in payload["entries"]} >= {"tw-monthly-revenue"}


def test_sse_skips_notifications_and_joins_multiline_data():
    body = (
        'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress"}\n\n'
        'event: message\ndata: {"jsonrpc":"2.0",\ndata: "id":7,"result":{"ok":true}}\n\n'
    )
    assert parse_rpc_response("text/event-stream", body, 7)["result"] == {"ok": True}


def test_plain_json_response():
    assert parse_rpc_response("application/json", '{"id":1,"result":{}}', 1)["result"] == {}


def test_text_content_is_parsed_without_structured_content():
    result = {"content": [{"type": "text", "text": '{"a": 1}'}]}
    assert extract_tool_payload(result) == {"a": 1}


def test_response_without_matching_id_is_an_error():
    with pytest.raises(McpError) as err:
        parse_rpc_response("text/event-stream", 'data: {"id":2,"result":{}}\n\n', 1)
    assert err.value.code == "invalid_mcp_response"


@pytest.mark.parametrize(
    "url",
    [
        "http://equitylayer.io/mcp",
        "http://192.168.0.10:3420/mcp",
        "http://localhost:3420/admin",
        "https://localhost/mcp/x",
        "https://evil.example/mcp",
        "https://equitylayer.io.evil.example/mcp",
        "https://sub.equitylayer.io/mcp",
        "https://user:pw@equitylayer.io/mcp",
        "https://equitylayer.io:8443/mcp",
        "https://equitylayer.io/admin",
        "https://equitylayer.io/mcp?x=1",
        "not a url",
        "",
    ],
)
def test_url_allowlist_refuses(url):
    with pytest.raises(McpError) as err:
        validate_mcp_url(url)
    assert err.value.code == "invalid_mcp_url"


@pytest.mark.parametrize(
    "url",
    [
        "https://equitylayer.io/mcp",
        "https://equitylayer.io/mcp/full",
        "http://localhost:3420/mcp",
        "http://127.0.0.1:3420/mcp/full",
    ],
)
def test_url_allowlist_accepts(url):
    assert validate_mcp_url(url) == url



def _client(handler):
    return McpClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    "status,code",
    [(402, "payment_required"), (401, "agent_authentication_required"), (500, "upstream_unavailable")],
)
def test_http_status_maps_to_stable_codes(status, code):
    with pytest.raises(McpError) as err:
        _client(lambda r: httpx.Response(status)).call_tool("list_registry")
    assert err.value.code == code


def test_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/mcp"})

    with pytest.raises(McpError) as err:
        _client(handler).call_tool("list_registry")
    assert err.value.code == "upstream_unavailable"
    assert calls == ["https://equitylayer.io/mcp"]


def test_transient_gateway_error_retries_once():
    responses = [
        httpx.Response(503),
        httpx.Response(200, headers={"content-type": "text/event-stream"}, text=fixture_text("list_registry")),
    ]
    assert _client(lambda r: responses.pop(0)).call_tool("list_registry")["entries"]


def test_timeout_becomes_upstream_unavailable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(McpError) as err:
        _client(handler).call_tool("list_registry")
    assert err.value.code == "upstream_unavailable"


def test_is_error_string_and_object_shapes():
    def sse(name):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=fixture_text(name))

    with pytest.raises(McpError) as err:
        _client(lambda r: sse("get_research_pack_unknown")).call_tool("get_research_pack")
    assert err.value.code == "unknown_research_pack"
    assert err.value.details["known_pack_ids"] == ["tw-monthly-revenue"]

    with pytest.raises(McpError) as err:
        _client(lambda r: sse("check_harness_invalid")).call_tool("check_thesis_harness")
    assert err.value.code == "invalid_arguments"
    assert err.value.message.startswith("harness.why")


def test_x402_in_rpc_error_is_payment_required():
    def handler(request):
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "x402 challenge"}},
        )

    with pytest.raises(McpError) as err:
        _client(handler).call_tool("get_research_pack")
    assert err.value.code == "payment_required"
