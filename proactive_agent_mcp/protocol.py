"""
Model Context Protocol (MCP) JSON-RPC 2.0 primitives.

Implements the subset of JSON-RPC 2.0 that MCP relies on, plus the MCP
capability/argument dataclasses used to advertise the server surface.

Protocol versions
-----------------
The server negotiates downwards against the version requested by the client so
that it can talk to both modern clients (which expect structured tool output)
and older ones pinned to the original 2024-11-05 revision.
"""

from dataclasses import dataclass, field
from typing import Any

#: Newest revision this server implements, preferred during negotiation.
MCP_PROTOCOL_VERSION = "2025-06-18"

#: Every revision this server can speak, newest first.
SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

#: The original revision, kept for tests and legacy clients.
LEGACY_PROTOCOL_VERSION = "2024-11-05"

#: Revisions that understand the ``structuredContent`` field on tool results.
STRUCTURED_OUTPUT_VERSIONS = frozenset({"2025-06-18"})

SERVER_NAME = "proactive-agent-mcp"
SERVER_VERSION = "1.1.0"

# Standard JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def negotiate_protocol_version(requested: str | None) -> str:
    """
    Choose the protocol revision to answer an ``initialize`` request with.

    Clients that request a revision we understand get that exact revision.
    Clients that request something unknown are answered with our newest
    supported revision, which is the behaviour the MCP specification asks for.
    """
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return MCP_PROTOCOL_VERSION


class MCPError(Exception):
    """A JSON-RPC level failure that should be surfaced to the client as an error object."""

    def __init__(self, code: int, message: str, data: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        err: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


def is_notification(message: Any) -> bool:
    """
    Return True when a message is a JSON-RPC notification.

    JSON-RPC 2.0 requires that a server never replies to a notification, so the
    dispatcher checks this before producing a response.
    """
    return isinstance(message, dict) and "id" not in message


@dataclass
class Tool:
    name: str
    description: str
    inputSchema: dict[str, Any]
    outputSchema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None

    def to_dict(self, include_structured_output: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema,
        }
        if include_structured_output and self.outputSchema is not None:
            out["outputSchema"] = self.outputSchema
        if self.annotations:
            out["annotations"] = self.annotations
        return out


@dataclass
class Resource:
    uri: str
    name: str
    description: str
    mimeType: str = "application/json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mimeType,
        }


@dataclass
class PromptArgument:
    name: str
    description: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required,
        }


@dataclass
class Prompt:
    name: str
    description: str
    arguments: list[PromptArgument] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": [a.to_dict() for a in self.arguments],
        }


def make_jsonrpc_response(req_id: int | str | None, result: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result,
    }


def make_jsonrpc_error(
    req_id: int | str | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err,
    }
