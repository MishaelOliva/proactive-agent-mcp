"""
Proactive Agent MCP (Model Context Protocol) Server Engine.
Implements the JSON-RPC 2.0 stdio transport conforming to MCP 2024-11-05 spec.
"""

import sys
import json
import logging
from typing import Any, Dict, Optional

from .protocol import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    PARSE_ERROR,
    METHOD_NOT_FOUND,
    INVALID_PARAMS,
    make_jsonrpc_response,
    make_jsonrpc_error
)
from .tools import TOOLS, dispatch_tool
from .resources import RESOURCES, read_resource
from .prompts import PROMPTS, get_prompt_message

# Configure logging strictly to stderr to prevent polluting stdout JSON-RPC stream
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [MCP] %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger("proactive_agent_mcp")


class MCPServer:
    def __init__(self, name: str = SERVER_NAME, version: str = SERVER_VERSION):
        self.name = name
        self.version = version
        self.initialized = False

    def handle_request(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        req_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})

        logger.debug(f"Handling method '{method}' (id: {req_id})")

        # 1. Initialize
        if method == "initialize":
            self.initialized = True
            return make_jsonrpc_response(req_id, {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"subscribe": False, "listChanged": False},
                    "prompts": {"listChanged": False}
                },
                "serverInfo": {
                    "name": self.name,
                    "version": self.version
                }
            })

        # 2. Initialized Notification (no response needed)
        if method == "notifications/initialized":
            logger.info("Client completed initialization handshake.")
            return None

        # 3. Ping
        if method == "ping":
            return make_jsonrpc_response(req_id, {})

        # 4. Tools
        if method == "tools/list":
            return make_jsonrpc_response(req_id, {
                "tools": [t.to_dict() for t in TOOLS]
            })

        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                result = dispatch_tool(tool_name, arguments)
                return make_jsonrpc_response(req_id, {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2)
                        }
                    ],
                    "isError": False
                })
            except Exception as e:
                logger.error(f"Error calling tool '{tool_name}': {e}", exc_info=True)
                return make_jsonrpc_response(req_id, {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"error": str(e)}, indent=2)
                        }
                    ],
                    "isError": True
                })

        # 5. Resources
        if method == "resources/list":
            return make_jsonrpc_response(req_id, {
                "resources": [r.to_dict() for r in RESOURCES]
            })

        if method == "resources/read":
            uri = params.get("uri")
            try:
                res = read_resource(uri)
                return make_jsonrpc_response(req_id, res)
            except Exception as e:
                return make_jsonrpc_error(req_id, INVALID_PARAMS, str(e))

        # 6. Prompts
        if method == "prompts/list":
            return make_jsonrpc_response(req_id, {
                "prompts": [p.to_dict() for p in PROMPTS]
            })

        if method == "prompts/get":
            prompt_name = params.get("name")
            arguments = params.get("arguments", {})
            try:
                prompt_data = get_prompt_message(prompt_name, arguments)
                return make_jsonrpc_response(req_id, prompt_data)
            except Exception as e:
                return make_jsonrpc_error(req_id, INVALID_PARAMS, str(e))

        # Unknown method
        logger.warning(f"Unknown method requested: {method}")
        return make_jsonrpc_error(req_id, METHOD_NOT_FOUND, f"Method '{method}' not implemented.")

    def run_stdio(self):
        """
        Runs stdio event loop reading JSON-RPC messages line by line.
        """
        logger.info(f"Starting {self.name} v{self.version} stdio listener...")
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as err:
                err_resp = make_jsonrpc_error(None, PARSE_ERROR, "Invalid JSON received.", str(err))
                sys.stdout.write(json.dumps(err_resp) + "\n")
                sys.stdout.flush()
                continue

            response = self.handle_request(message)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()


def main():
    server = MCPServer()
    try:
        server.run_stdio()
    except KeyboardInterrupt:
        logger.info("Server terminated by signal.")
    except Exception as e:
        logger.critical(f"Server crashed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
