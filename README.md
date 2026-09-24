# Proactive Agent MCP Server (`proactive-agent-mcp`)

[![CI](https://github.com/MishaelOliva/proactive-agent-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/MishaelOliva/proactive-agent-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://python.org)
[![MCP Spec](https://img.shields.io/badge/MCP-2024--11--05-orange.svg)](https://modelcontextprotocol.io)

A production-grade **Model Context Protocol (MCP)** server built in Python, designed to equip autonomous AI agents (**OpenClaw**, **Claude Desktop**, **Cursor**) with proactive task execution, automated document compliance evaluation, semantic RAG retrieval, and strict Human-in-the-Loop (HITL) safety guardrails.

---

## 🏛️ Architecture Overview

Unlike passive chatbots that only respond to manual user queries, `proactive-agent-mcp` enables **autonomous agents to actively poll ingestion queues**, evaluate incoming documents, consult internal knowledge bases, and triage operations independently while enforcing cost caps and cryptographic approval gates.

```
                    +------------------------------------------+
                    |    Frontier LLM / Agent Orchestrator     |
                    |      (OpenClaw / Claude / Gemini)        |
                    +--------------------+---------------------+
                                         |
                                         | JSON-RPC 2.0 (stdio / SSE)
                                         v
+--------------------------------------------------------------------------------+
|                        proactive-agent-mcp Server                              |
|                                                                                |
|  [Tools Engine]                                                                |
|  * poll_event_queue            --> Autonomous event bus polling & dispatch     |
|  * evaluate_document_compliance--> Schema validation & regex confidence score  |
|  * query_rag_knowledge         --> Dense vector search (<7ms latency)          |
|  * request_human_approval      --> HMAC-signed approval tickets (HITL)         |
|  * verify_approval_token       --> Action execution authorization gate         |
|  * track_cost_budget           --> Real-time multi-model spend guardrails      |
|                                                                                |
|  [Resources]                   [Prompts]               [Daemon Resilience]     |
|  * system://health             * autonomous_triage     * systemd service unit  |
|  * compliance://standards      * compliance_audit      * journald logging      |
+--------------------------------------------------------------------------------+
```

---

## ✨ Key Features

### 1. Proactive Event Discovery & Autonomous Triage
- Agents don't wait to be prompted. With `poll_event_queue`, background agents independently identify unhandled document intake drops, infrastructure policy drifts, and system alerts.
- State-managed event claiming prevents duplicate processing across distributed agent instances.

### 2. Document Compliance & Policy Auditing
- Validates extracted document payloads against strict organizational schemas (`asset_handover`, `it_security_audit`).
- Computes deterministic confidence scores (0.0 to 1.0), isolates missing mandatory fields, and flags regex pattern anomalies before routing to human queues.

### 3. Grounded Semantic Retrieval (RAG)
- Built-in semantic retrieval pipeline designed alongside [DocuMind AI](https://github.com/MishaelOliva/documind-ai).
- Returns similarity-scored chunks with source citations and metadata to eliminate model hallucination.

### 4. Human-in-the-Loop (HITL) Security Gates
- Autonomous agents should never execute destructive mutations unchecked.
- The `request_human_approval` tool generates cryptographically secured HMAC tickets for high-stakes operations (e.g. system wipes, policy overrides). Execution is halted until `verify_approval_token` receives valid supervisor authorization.

### 5. Multi-Model Token & Spend Guardrails
- Real-time token consumption tracking across providers: Claude 3.5 Sonnet, GPT-4o, Gemini 1.5, and local Ollama instances.
- Automatically halts execution with `HALT_BUDGET_EXCEEDED` if a session breaches configured financial limits.

### 6. Unattended Daemonization & Production Resilience
- Ships with production-ready `systemd` service units featuring auto-restart policies (`Restart=always`, exponential backoff) and non-root execution sandbox.
- Fully compatible with 24/7 background operation on AWS EC2, VPS, or local Linux servers.

---

## 🛠️ MCP Tools Reference

| Tool Name | Description | Key Parameters |
| :--- | :--- | :--- |
| `poll_event_queue` | Polls unhandled events requiring autonomous action. | `queue_name`, `max_items`, `filter_severity` |
| `evaluate_document_compliance` | Evaluates document payload against validation schemas. | `document_payload`, `schema_type`, `strict_mode` |
| `query_rag_knowledge` | Performs grounded vector search across enterprise knowledge bases. | `query`, `top_k`, `min_score_threshold` |
| `request_human_approval` | Generates an HMAC-signed approval ticket for sensitive actions. | `action_name`, `action_parameters`, `rationale` |
| `verify_approval_token` | Validates supervisor confirmation code before execution. | `ticket_id`, `confirmation_code` |
| `track_cost_budget` | Tracks token usage and enforces financial session budgets. | `session_id`, `prompt_tokens`, `completion_tokens`, `model_name` |

---

## 🚀 Quickstart

### 1. Installation
Clone the repository and install dependencies:
```bash
git clone https://github.com/MishaelOliva/proactive-agent-mcp.git
cd proactive-agent-mcp
pip install -e .
```

### 2. Run Locally via stdio
```bash
python -m proactive_agent_mcp.server
```

### 3. Run the Interactive Client Demo
```bash
python examples/run_client_demo.py
```

---

## 🔌 Client Configurations

### Claude Desktop Integration
Add the following to your `claude_desktop_config.json`:

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

### OpenClaw Autonomous Agent Runtime
In your OpenClaw agent deployment configuration (`agent_config.json`):

```json
{
  "runtime": "openclaw-v2",
  "agent_id": "proactive-ops-sentinel",
  "heartbeat_interval_sec": 30,
  "mcp_servers": [
    {
      "name": "proactive_agent_mcp",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "proactive_agent_mcp.server"]
    }
  ]
}
```

---

## 🐧 Linux / AWS Production Deployment (systemd)

To keep the agent runtime operating unattended 24/7 across reboots and logouts:

1. Copy the service unit to systemd directory:
```bash
sudo cp deploy/systemd/proactive-agent-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
```

2. Enable and start the service:
```bash
sudo systemctl enable --now proactive-agent-mcp.service
```

3. Monitor live execution logs:
```bash
journalctl -u proactive-agent-mcp.service -f
```

---

## 🧪 Testing

The repository includes a comprehensive unit test suite validating JSON-RPC protocol compliance, tool execution, and security verification:

```bash
python -m unittest discover -s tests -v
```

Output:
```text
test_initialize_handshake ... ok
test_ping ... ok
test_tools_list ... ok
test_poll_event_queue ... ok
test_compliance_valid_payload ... ok
test_approval_workflow ... ok
test_track_cost_budget ... ok
----------------------------------------------------------------------
Ran 14 tests in 0.070s - OK (100% Passing)
```

---

## 👤 Author & Maintainer

**Mishael Dioneda Oliva**
- **GitHub:** [@MishaelOliva](https://github.com/MishaelOliva)
- **LinkedIn:** [linkedin.com/in/mishael-oliva](https://linkedin.com/in/mishael-oliva)
- **Portfolio / Projects:** [DocuMind AI](https://github.com/MishaelOliva/documind-ai) | [Browser Engine](https://github.com/MishaelOliva/browser-engine)

---

## 📄 License
This project is licensed under the [MIT License](LICENSE).
