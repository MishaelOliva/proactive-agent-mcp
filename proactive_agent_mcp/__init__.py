"""
Proactive Agent MCP Server Package.
"""

from .server import MCPServer, main
from .protocol import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    Tool,
    Resource,
    Prompt
)

__version__ = SERVER_VERSION
__all__ = [
    "MCPServer",
    "main",
    "MCP_PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "Tool",
    "Resource",
    "Prompt"
]
