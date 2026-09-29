"""
Proactive Agent MCP server package.

Importing this package is side-effect free with respect to logging: a
:class:`logging.NullHandler` is attached so the library never reconfigures the
host application's root logger. ``proactive_agent_mcp.server.main`` configures
real logging when the process starts.
"""

import logging

from .protocol import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    Prompt,
    PromptArgument,
    Resource,
    Tool,
)
from .server import MCPServer, main
from .validation import ToolInputError, validate_arguments

__version__ = SERVER_VERSION

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "MCPServer",
    "main",
    "MCP_PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "Tool",
    "Resource",
    "Prompt",
    "PromptArgument",
    "ToolInputError",
    "validate_arguments",
    "__version__",
]
