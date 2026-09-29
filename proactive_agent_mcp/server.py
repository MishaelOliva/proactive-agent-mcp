"""
Proactive Agent MCP server: JSON-RPC 2.0 dispatch over stdio.

Transport
---------
Messages are newline-delimited JSON on stdin; responses go to stdout. Logging is
routed to stderr only, and is configured when the process actually starts
rather than at import time, so importing this package as a library does not
reconfigure the host application's logging.

Protocol conformance
--------------------
The dispatcher implements the parts of JSON-RPC 2.0 and MCP that clients
actually exercise, and in particular gets three rules right that are easy to
get wrong:

* Notifications are never answered. A message without an ``id`` produces no
  response at all, which is what clients sending ``notifications/cancelled``
  expect.
* Requests other than ``initialize`` and ``ping`` are refused until the
  handshake has completed.
* Protocol version is negotiated against the client's request rather than
  always answered with a hard-coded string.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, Optional

from .prompts import PROMPTS, get_prompt_message
from .protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    LEGACY_PROTOCOL_VERSION,
    MCP_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    SERVER_NAME,
    SERVER_VERSION,
    STRUCTURED_OUTPUT_VERSIONS,
    SUPPORTED_PROTOCOL_VERSIONS,
    is_notification,
    make_jsonrpc_error,
    make_jsonrpc_response,
    negotiate_protocol_version,
)
from .resources import RESOURCES, read_resource
from .tools import (
    BUDGET_EXEMPT_TOOLS,
    TOOLS,
    ToolInputError,
    dispatch_tool,
    enforce_budget,
    get_active_session,
)
from .tools.guardrails import BudgetExceeded

logger = logging.getLogger("proactive_agent_mcp")

#: Methods a client may send before completing the initialize handshake.
PRE_INIT_METHODS = frozenset({"initialize", "ping"})

#: Notifications the server acts on rather than merely acknowledging.
KNOWN_NOTIFICATIONS = frozenset(
    {
        "notifications/initialized",
        "notifications/cancelled",
        "notifications/progress",
        "notifications/roots/list_changed",
    }
)

#: Page size used when a client does not request a specific one.
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

Request = dict[str, Any]
Response = Optional[dict[str, Any]]


class MCPServer:
    """A single-process MCP server speaking JSON-RPC 2.0 over stdio."""

    def __init__(self, name: str = SERVER_NAME, version: str = SERVER_VERSION):
        self.name = name
        self.version = version
        self.initialized = False
        self.protocol_version = LEGACY_PROTOCOL_VERSION
        self.client_info: dict[str, Any] = {}
        self.log_level = "info"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def supports_structured_output(self) -> bool:
        return self.protocol_version in STRUCTURED_OUTPUT_VERSIONS

    @staticmethod
    def _paginate(items: list[dict[str, Any]], cursor: str | None, key: str) -> dict[str, Any]:
        """Cursor pagination over a materialised list.

        Results are returned under the method's own key (``tools``, ``resources``,
        ``prompts``) so the response keeps the shape the MCP schema requires, with
        ``nextCursor`` added alongside when more remain. The cursor is the index of
        the next item, which is sufficient for an in-process registry that does not
        change underneath a listing.
        """
        try:
            start = int(cursor) if cursor else 0
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid cursor: expected an integer offset.") from exc
        if start < 0 or start > len(items):
            raise ValueError("Invalid cursor: out of range.")

        page = items[start : start + DEFAULT_PAGE_SIZE]
        result: dict[str, Any] = {key: page}
        next_cursor = start + len(page)
        if next_cursor < len(items):
            result["nextCursor"] = str(next_cursor)
        return result

    def _tool_result(self, result: Any) -> dict[str, Any]:
        """Wrap a handler return value in MCP tool-result shape."""
        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": json.dumps(result, indent=2, default=str)}],
            "isError": False,
        }
        if self.supports_structured_output:
            payload["structuredContent"] = result
        return payload

    def _tool_error(self, message: str, **extra: Any) -> dict[str, Any]:
        body: dict[str, Any] = {"error": message, **extra}
        return {
            "content": [{"type": "text", "text": json.dumps(body, indent=2, default=str)}],
            "isError": True,
        }

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def handle_message(self, message: Any) -> Response | list[dict[str, Any]]:
        """
        Dispatch one parsed message.

        Returns ``None`` for notifications, a single response object for a
        request, or a list for a batch request.
        """
        # JSON-RPC 2.0 batch: an array of messages.
        if isinstance(message, list):
            if not message:
                return make_jsonrpc_error(None, INVALID_REQUEST, "Batch request must not be empty.")
            responses = [self.handle_message(item) for item in message]
            return [r for r in responses if r is not None] or None

        if not isinstance(message, dict):
            return make_jsonrpc_error(None, INVALID_REQUEST, "Request must be a JSON object.")

        if message.get("jsonrpc") != "2.0":
            return make_jsonrpc_error(
                message.get("id"),
                INVALID_REQUEST,
                'Missing or invalid "jsonrpc" version; expected "2.0".',
            )

        method = message.get("method")
        if not isinstance(method, str) or not method:
            return make_jsonrpc_error(
                message.get("id"), INVALID_REQUEST, 'Missing or invalid "method".'
            )

        # Notifications never get a reply, not even an error.
        if is_notification(message):
            self._handle_notification(method, message.get("params") or {})
            return None

        params = message.get("params") or {}
        if not isinstance(params, dict):
            return make_jsonrpc_error(
                message.get("id"), INVALID_PARAMS, '"params" must be an object.'
            )

        return self.handle_request(message)

    def _handle_notification(self, method: str, params: dict[str, Any]) -> None:
        if method == "notifications/initialized":
            self.initialized = True
            logger.info(
                "Client completed handshake with %s",
                self.client_info.get("name", "unknown client"),
            )
        elif method == "notifications/cancelled":
            request_id = params.get("requestId")
            logger.info("Client cancelled request %s", request_id)
        elif method in KNOWN_NOTIFICATIONS:
            logger.debug("Ignoring notification %s", method)
        else:
            logger.debug("Unrecognised notification %s", method)

    def handle_request(self, message: Request) -> Response:
        """Dispatch a single JSON-RPC request to its method handler."""
        req_id = message.get("id")
        method = message["method"]
        params = message.get("params") or {}

        if req_id is None:
            # An explicit null id is still a request, but the id must be a string
            # or a number; treat it as malformed rather than guessing.
            return make_jsonrpc_error(
                None, INVALID_REQUEST, 'Request "id" must be a string or a number.'
            )

        if method not in PRE_INIT_METHODS and not self.initialized:
            return make_jsonrpc_error(
                req_id,
                INVALID_REQUEST,
                f"Received '{method}' before initialization; call 'initialize' first.",
            )

        handlers = {
            "initialize": self._handle_initialize,
            "ping": lambda _p: {},
            "tools/list": self._handle_tools_list,
            "tools/call": self._handle_tools_call,
            "resources/list": self._handle_resources_list,
            "resources/read": self._handle_resources_read,
            "prompts/list": self._handle_prompts_list,
            "prompts/get": self._handle_prompts_get,
            "logging/setLevel": self._handle_set_log_level,
        }

        handler = handlers.get(method)
        if handler is None:
            logger.warning("Unknown method requested: %s", method)
            return make_jsonrpc_error(
                req_id, METHOD_NOT_FOUND, f"Method '{method}' not implemented."
            )

        try:
            return make_jsonrpc_response(req_id, handler(params))
        except ValueError as exc:
            return make_jsonrpc_error(req_id, INVALID_PARAMS, str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unhandled error in %s", method)
            return make_jsonrpc_error(req_id, INTERNAL_ERROR, str(exc))

    # ------------------------------------------------------------------
    # Method handlers
    # ------------------------------------------------------------------

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        self.protocol_version = negotiate_protocol_version(requested)
        self.client_info = params.get("clientInfo") or {}
        if requested and requested not in SUPPORTED_PROTOCOL_VERSIONS:
            logger.info(
                "Client requested protocol %s; answering with %s",
                requested,
                self.protocol_version,
            )

        return {
            "protocolVersion": self.protocol_version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
                "logging": {},
            },
            "serverInfo": {"name": self.name, "version": self.version},
            "instructions": (
                "Poll the triage queue, evaluate documents, and gate sensitive "
                "actions behind request_human_approval. Settle claimed events with "
                "complete_event when finished."
            ),
        }

    def _handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        items = [
            tool.to_dict(include_structured_output=self.supports_structured_output)
            for tool in TOOLS
        ]
        return self._paginate(items, params.get("cursor"), "tools")

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError('"params.name" must be a non-empty string.')

        # Server-side enforcement: an exhausted budget stops the work rather
        # than reporting a status the caller may choose to ignore.
        if tool_name not in BUDGET_EXEMPT_TOOLS:
            try:
                enforce_budget()
            except BudgetExceeded as exc:
                return self._tool_error(
                    exc.status["error"],
                    status="HALT_BUDGET_EXCEEDED",
                    reason=exc.status["reason"],
                    session_id=get_active_session(),
                    budget=exc.status,
                )

        try:
            result = dispatch_tool(tool_name, params.get("arguments"))
        except ToolInputError as exc:
            problems = getattr(exc, "problems", None)
            if problems is None:
                raise ValueError(str(exc)) from exc
            return self._tool_error(str(exc), problems=problems)
        except Exception as exc:
            logger.error("Error calling tool '%s': %s", tool_name, exc, exc_info=True)
            return self._tool_error(f"{type(exc).__name__}: {exc}")

        return self._tool_result(result)

    def _handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._paginate([r.to_dict() for r in RESOURCES], params.get("cursor"), "resources")

    def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str) or not uri:
            raise ValueError('"params.uri" must be a non-empty string.')
        return read_resource(uri)

    def _handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._paginate([p.to_dict() for p in PROMPTS], params.get("cursor"), "prompts")

    def _handle_prompts_get(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError('"params.name" must be a non-empty string.')
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError('"params.arguments" must be an object.')
        return get_prompt_message(name, arguments)

    def _handle_set_log_level(self, params: dict[str, Any]) -> dict[str, Any]:
        level = params.get("level")
        allowed = {"debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"}
        if level not in allowed:
            raise ValueError(f"Unsupported log level '{level}'. Expected one of {sorted(allowed)}.")
        self.log_level = level
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        return {}

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _write(self, payload: Any) -> None:
        sys.stdout.write(json.dumps(payload, default=str) + "\n")
        sys.stdout.flush()

    def run_stdio(self) -> None:
        """Read newline-delimited JSON-RPC from stdin until the stream closes."""
        logger.info("Starting %s v%s (protocol %s)", self.name, self.version, MCP_PROTOCOL_VERSION)
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                self._write(
                    make_jsonrpc_error(None, PARSE_ERROR, "Invalid JSON received.", str(exc))
                )
                continue

            response = self.handle_message(message)
            if response is None:
                continue
            if isinstance(response, list):
                if response:
                    self._write(response)
            else:
                self._write(response)

        logger.info("Input stream closed; shutting down.")


def main() -> int:
    """Console entry point. Configures logging here rather than at import time."""
    logging.basicConfig(
        level=os.environ.get("MCP_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s [%(levelname)s] [MCP] %(message)s",
        stream=sys.stderr,
    )
    try:
        MCPServer().run_stdio()
    except KeyboardInterrupt:
        logger.info("Server terminated by signal.")
    except Exception:
        logger.critical("Server crashed", exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
