# proactive-agent-mcp

A Model Context Protocol (MCP) tool server in Python that exposes task queues, schema validation, semantic retrieval, and human-in-the-loop approval gates over stdio.

[![CI](https://github.com/MishaelOliva/proactive-agent-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/MishaelOliva/proactive-agent-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/Python-3.11%2B-brightgreen.svg)](https://python.org)
[![MCP Spec](https://img.shields.io/badge/MCP-2024--11--05-orange.svg)](https://modelcontextprotocol.io)

## What it does

- **Ingestion triage**: Polls an event queue to retrieve unprocessed operational items (`poll_event_queue`).
- **Compliance evaluation**: Validates document payloads against predefined schemas (such as asset handovers) and flags missing fields (`evaluate_document_compliance`).
- **Grounded knowledge retrieval**: Queries reference knowledge chunks with similarity scoring and latency tracking (`query_rag_knowledge`).
- **Human-in-the-loop gates**: Generates HMAC-signed approval tickets for sensitive actions and verifies confirmation tokens before execution (`request_human_approval`, `verify_approval_token`).
- **Spend tracking**: Accumulates token usage across models and halts execution if the configured budget is exceeded (`track_cost_budget`).

## Architecture / How it works

The server implements the Model Context Protocol (spec version 2024-11-05) using standard JSON-RPC 2.0 messages over standard input and output (`stdio`). Diagnostic logs are routed exclusively to `stderr` so they do not interfere with the protocol stream on `stdout`.

```
+------------------------------------------------+
|     Client (Claude Desktop / Cursor / IDE)     |
+-----------------------+------------------------+
                        |
                        | JSON-RPC 2.0 via stdio
                        v
+------------------------------------------------+
|              proactive-agent-mcp               |
|                                                |
|  Tools:                                        |
|   - poll_event_queue                           |
|   - evaluate_document_compliance               |
|   - query_rag_knowledge                        |
|   - request_human_approval                     |
|   - verify_approval_token                      |
|   - track_cost_budget                          |
|                                                |
|  Resources:                                    |
|   - system://health                            |
|   - compliance://standards                     |
|                                                |
|  Prompts:                                      |
|   - autonomous_triage                          |
|   - compliance_audit                           |
+------------------------------------------------+
```

Event storage and RAG knowledge stores in this repository are in-memory reference implementations designed for local testing and agent development.

## Quick start

```bash
git clone https://github.com/MishaelOliva/proactive-agent-mcp.git
cd proactive-agent-mcp
pip install -e .
python -m proactive_agent_mcp.server
```

You can also run the interactive client demonstration script:

```bash
python examples/run_client_demo.py
```

## Configuration

### Client Setup

#### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "proactive-agent": {
      "command": "python",
      "args": ["-m", "proactive_agent_mcp.server"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

#### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "proactive-agent": {
      "command": "python -m proactive_agent_mcp.server"
    }
  }
}
```

### Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `MCP_SIGNING_SECRET` | Secret key used to generate and verify HMAC-SHA256 approval tokens | `dev-insecure-secret-change-in-production` |
| `PYTHONUNBUFFERED` | Ensures standard output flushes immediately for JSON-RPC messages | `1` (recommended) |

## Testing

The test suite validates JSON-RPC protocol compliance (initialize, tools/list, resources, prompts, error handling), tool dispatch, and security token verification:

```bash
python -m unittest discover -s tests -v
```

18 tests run in approximately 0.04s.

## Known limitations

- **Transport support**: Only stdio transport is supported. Server-Sent Events (SSE) and HTTP transports are not implemented.
- **In-memory storage**: The event queue and RAG chunk store reside in memory and reset whenever the process restarts.
- **Synchronous execution**: Requests are processed sequentially on a single thread.

## License

This project is licensed under the [MIT License](LICENSE).

---
*Built by [Mishael Oliva](https://github.com/MishaelOliva) • [LinkedIn](https://linkedin.com/in/mishael-oliva)*
