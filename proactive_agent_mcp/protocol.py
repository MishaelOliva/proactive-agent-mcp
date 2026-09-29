"""
Model Context Protocol (MCP) JSON-RPC 2.0 Specification Implementation.
Conforms to MCP Specification (2024-11-05).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "proactive-agent-mcp"
SERVER_VERSION = "1.0.0"

# Standard JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Optional[Any] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> Dict[str, Any]:
        err = {"code": self.code, "message": self.message}
        if self.data is not None:
            err["data"] = self.data
        return err


@dataclass
class Tool:
    name: str
    description: str
    inputSchema: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.inputSchema
        }


@dataclass
class Resource:
    uri: str
    name: str
    description: str
    mimeType: str = "application/json"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mimeType
        }


@dataclass
class PromptArgument:
    name: str
    description: str
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "required": self.required
        }


@dataclass
class Prompt:
    name: str
    description: str
    arguments: List[PromptArgument] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": [a.to_dict() for a in self.arguments]
        }


def make_jsonrpc_response(req_id: Union[int, str, None], result: Any) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": result
    }


def make_jsonrpc_error(req_id: Union[int, str, None], code: int, message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    err: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": err
    }
