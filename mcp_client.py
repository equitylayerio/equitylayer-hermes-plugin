"""Minimal Streamable HTTP MCP client for the EquityLayer endpoint."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

import httpx

DEFAULT_MCP_URL = "https://equitylayer.io/mcp"
ALLOWED_HOST = "equitylayer.io"
ALLOWED_PATHS = ("/mcp", "/mcp/full")
USER_AGENT = "EquityLayerHermesPlugin/0.2"
TIMEOUT_SECONDS = 45.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
RETRYABLE_STATUS = (502, 503, 504)


class McpError(Exception):
    """A failed MCP call. `code` is stable and safe to branch on."""

    def __init__(self, code: str, message: str = "", *, details: Any = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details


LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def validate_mcp_url(url: str) -> str:
    """Allow HTTPS to equitylayer.io, or plain HTTP to this machine for development.

    Nothing else is accepted, so a config value can never point the plugin at another host.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except (ValueError, AttributeError) as exc:
        raise McpError("invalid_mcp_url", f"Could not parse MCP URL: {url!r}") from exc
    production = parts.scheme == "https" and parts.hostname == ALLOWED_HOST and port in (None, 443)
    loopback = parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS
    allowed = (
        (production or loopback)
        and not parts.username
        and not parts.password
        and parts.path.rstrip("/") in ALLOWED_PATHS
        and not parts.query
        and not parts.fragment
    )
    if not allowed:
        raise McpError(
            "invalid_mcp_url",
            "mcp_url must be https://equitylayer.io/mcp, or http://localhost:<port>/mcp for development.",
        )
    return url.rstrip("/")


def parse_rpc_response(content_type: str, body: str, request_id: int) -> dict:
    """Return the JSON-RPC message for `request_id` from a JSON or SSE body."""
    if "text/event-stream" in (content_type or ""):
        messages = _sse_messages(body)
    else:
        try:
            messages = [json.loads(body)]
        except ValueError as exc:
            raise McpError("invalid_mcp_response", "The MCP response was not JSON.") from exc
    for message in messages:
        if isinstance(message, dict) and message.get("id") == request_id:
            return message
    raise McpError("invalid_mcp_response", "The MCP response had no result for this request.")


def _sse_messages(body: str) -> list:
    """Decode SSE `data:` fields. Events end at a blank line; data may span lines."""
    messages: list = []
    data: list[str] = []

    def flush() -> None:
        if data:
            try:
                messages.append(json.loads("\n".join(data)))
            except ValueError:
                pass  # Skip a malformed frame; a missing result is reported by the caller.
            data.clear()

    for line in body.splitlines():
        if not line:
            flush()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))
    flush()
    return messages


def extract_tool_payload(result: Any) -> dict:
    """Pull the tool's JSON object out of an MCP `tools/call` result."""
    if not isinstance(result, dict):
        raise McpError("invalid_mcp_response", "The MCP result was not an object.")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    text = "".join(
        block.get("text", "")
        for block in result.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    )
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"text": text}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _payload_error(payload: dict, is_error: bool) -> McpError | None:
    """Upstream errors appear as `{"error": "code"}` or `{"ok": false, "error": {...}}`."""
    error = payload.get("error")
    if isinstance(error, dict):
        return McpError(
            str(error.get("code") or "upstream_error"),
            str(error.get("message") or ""),
            details=error.get("details"),
        )
    if error:
        details = {k: v for k, v in payload.items() if k != "error"}
        return McpError(str(error), str(payload.get("message") or ""), details=details or None)
    if is_error or payload.get("ok") is False:
        text = str(payload.get("text") or payload.get("message") or "")
        # Schema failures come back as text; they mean the arguments, not the server, are wrong.
        if text.startswith("Input validation error"):
            return McpError("invalid_arguments", text.split(": ", 2)[-1] if ": " in text else text)
        return McpError("upstream_error", text)
    # A challenge body without an error field still must not read as research.
    if any(key in payload for key in ("x402", "payment_required", "payment_challenge")):
        return McpError("payment_required", "The server asked for payment.")
    return None


class McpClient:
    """Stateless `tools/call` client. The live server needs no session header."""

    def __init__(
        self,
        url: str = DEFAULT_MCP_URL,
        *,
        timeout: float = TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ):
        self.url = validate_mcp_url(url)
        self._timeout = timeout
        self._transport = transport
        self._next_id = 0

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        self._next_id += 1
        request_id = self._next_id
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        message = parse_rpc_response(response.headers.get("content-type", ""), response.text, request_id)
        if "error" in message:
            raise _rpc_error(message["error"])
        result = message.get("result")
        payload = extract_tool_payload(result)
        error = _payload_error(payload, bool(result.get("isError")))
        if error:
            raise error
        return payload

    def _post(self, payload: dict) -> httpx.Response:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": USER_AGENT,
        }
        # Every tool on this route is read-only, so one retry on a transient failure is safe.
        last_error = "The EquityLayer MCP did not respond."
        with httpx.Client(
            timeout=self._timeout, follow_redirects=False, transport=self._transport, trust_env=False
        ) as client:
            for _ in range(2):
                try:
                    response = client.post(self.url, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"Could not reach the EquityLayer MCP: {type(exc).__name__}."
                    continue
                if response.status_code in RETRYABLE_STATUS:
                    last_error = f"The EquityLayer MCP returned HTTP {response.status_code}."
                    continue
                _raise_for_status(response)
                return response
        raise McpError("upstream_unavailable", last_error)


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 402:
        raise McpError("payment_required", "The server returned HTTP 402.")
    if status in (401, 403):
        raise McpError("agent_authentication_required", f"The server returned HTTP {status}.")
    if status >= 300:
        raise McpError("upstream_unavailable", f"The EquityLayer MCP returned HTTP {status}.")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise McpError("invalid_mcp_response", "The MCP response was too large.")


def _rpc_error(error: Any) -> McpError:
    if not isinstance(error, dict):
        return McpError("mcp_protocol_error", str(error))
    message = str(error.get("message") or "")
    code = "payment_required" if error.get("code") == 402 or "x402" in message.lower() else "mcp_protocol_error"
    return McpError(code, message, details=error.get("data"))
