# proactive-agent-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) server in Python that exposes a proactive
triage queue, document compliance validation, grounded knowledge retrieval, and server-enforced
guardrails for autonomous agents. Speaks JSON-RPC 2.0 over stdio.

[![CI](https://github.com/MishaelOliva/proactive-agent-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/MishaelOliva/proactive-agent-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://python.org)
[![MCP: 2025-06-18](https://img.shields.io/badge/MCP-2025--06--18-orange.svg)](https://modelcontextprotocol.io)

## What it does

- **Proactive triage with leases.** `poll_event_queue` claims unprocessed events and takes a time-boxed
  lease on each. If the agent dies mid-triage the lease lapses and the event returns to the queue.
  `complete_event` and `release_event` settle or hand back work explicitly.
- **Document compliance evaluation.** `evaluate_document_compliance` checks extracted document fields
  against a declared schema, reporting missing fields, regex violations, a confidence score, and a
  risk level.
- **Grounded retrieval.** `query_rag_knowledge` ranks an in-repository corpus with sparse TF-IDF
  vectors and cosine similarity, returning measured latency and an explicit grounding verdict.
- **Human-in-the-loop gates.** `request_human_approval` parks a sensitive action behind an
  HMAC-SHA256 signed ticket. `verify_approval_token` checks a supervisor's confirmation code.
- **Cost enforcement.** `track_cost_budget` books token spend, and the server refuses further tool
  calls for any session that has exhausted its budget.

## Architecture

```
+--------------------------------------------------+
|        Client (Claude Desktop / Cursor / IDE)     |
+----------------------+---------------------------+
                       |
                       |  JSON-RPC 2.0 over stdio
                       v
+--------------------------------------------------+
|              proactive-agent-mcp                  |
|                                                  |
|  server.py     dispatch, negotiation, budgets    |
|  protocol.py   JSON-RPC + MCP primitives         |
|  validation.py pydantic argument enforcement     |
|                                                  |
|  tools/     triage, compliance, knowledge,       |
|             guardrails (HITL + cost)             |
|  resources/ system://health, compliance://standards
|  prompts/   autonomous_triage_loop,              |
|             compliance_audit_brief                |
+--------------------------------------------------+
```

The event queue and knowledge corpus are in-memory reference implementations. They reset on restart
and are not shared between replicas.

## Quick start

```bash
git clone https://github.com/MishaelOliva/proactive-agent-mcp.git
cd proactive-agent-mcp
pip install -e ".[dev]"
python -m proactive_agent_mcp.server
```

To watch a full triage session, including the human-approval round trip and budget enforcement:

```bash
python examples/run_client_demo.py
```

## Configuration

### Claude Desktop

```json
{
  "mcpServers": {
    "proactive-agent": {
      "command": "python",
      "args": ["-m", "proactive_agent_mcp.server"],
      "env": {
        "PYTHONUNBUFFERED": "1",
        "MCP_SIGNING_SECRET": "generate-with-openssl-rand-hex-32"
      }
    }
  }
}
```

### Cursor (`.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "proactive-agent": {
      "command": "python",
      "args": ["-m", "proactive_agent_mcp.server"],
      "env": {
        "MCP_SIGNING_SECRET": "generate-with-openssl-rand-hex-32"
      }
    }
  }
}
```

### Environment variables

| Variable | Purpose | Default |
| :--- | :--- | :--- |
| `MCP_SIGNING_SECRET` | Key for HMAC-SHA256 approval codes. **Set this.** An unset value produces a random per-process secret and logs a warning, so tokens do not survive a restart. | random, per process |
| `MCP_SESSION_BUDGET_USD` | Default per-session spend ceiling. | `5.0` |
| `MCP_LOG_LEVEL` | Log level for the stderr stream. | `INFO` |
| `PYTHONUNBUFFERED` | Flush stdout so responses are not buffered. | `1` recommended |

## Tools

| Tool | Purpose |
| :--- | :--- |
| `poll_event_queue` | Claim events under a lease. |
| `complete_event` | Settle a claimed event. |
| `release_event` | Return a claimed event to the queue. |
| `push_event` | Record an observation onto the queue. |
| `evaluate_document_compliance` | Validate extracted document fields. |
| `query_rag_knowledge` | Rank the corpus by TF-IDF cosine similarity. |
| `request_human_approval` | Park a sensitive action for human authorization. |
| `verify_approval_token` | Verify a supervisor's confirmation code. |
| `track_cost_budget` | Book token spend against a session. |
| `set_active_session` | Choose which session the budget guard charges. |

## Security model

The human-in-the-loop gate is a **worked pattern, not a production authorization system**. What it
does guarantee:

- Approval codes are **full 256-bit HMAC-SHA256** values, base32-encoded for legibility. They are not
  truncated.
- The signed payload binds the ticket id, action name, a SHA-256 digest of the action parameters, and
  the absolute expiry. A code cannot be re-pointed at a different action, swapped for different
  parameters, or replayed after expiry.
- The code is **recomputed** at verification time rather than read from a stored expected value, so a
  tampered ticket record invalidates its own code.
- Tickets are **single-use**, compared in **constant time**, and garbage-collected once settled.
- The confirmation code is **never returned** by `request_human_approval`. It must arrive through a
  channel the agent cannot reach.
- The signing secret has **no hardcoded default**. With `MCP_SIGNING_SECRET` unset, a random secret
  is generated at start-up, so a code cannot be derived from knowledge of this repository.

What it does **not** guarantee, and what a real deployment must add:

- Binding approvals to an authenticated human principal. The gate proves a holder of the secret
  approved, not *who*.
- Surviving a restart or spanning replicas. Tickets live in process memory.
- An authenticated delivery channel for the confirmation code.
- Protection against a sufficiently privileged caller with in-process access.

The budget guard **enforces** rather than advises: once a session exceeds its ceiling, the server
refuses non-guardrail tool calls. Accounting tools stay reachable so the agent can report honestly
rather than dead-ending.

## Testing

```bash
python -m unittest discover -s tests -t .
```

116 tests covering protocol conformance (initialization gating, notification suppression, version
negotiation, batching, pagination, error codes), tool behaviour, the HITL security properties, budget
enforcement, and an end-to-end stdio session against a real subprocess.

Several tests are explicit regression guards for defects fixed in v1.1.0: a confidence score that
capped a perfect document at 0.571, a hardcoded retrieval latency, a forgeable approval secret,
a mid-session budget change that was silently ignored, and an event queue that stranded work when an
agent crashed.

CI runs the suite on Python 3.10-3.12 with and without `MCP_SIGNING_SECRET` set, lints with ruff,
verifies the wheel installs in a clean environment, and smoke tests the container entrypoint.

## Limitations

- **Single process.** State is in memory, so the event queue, tickets, and budget ledger reset on
  restart and are not shared across replicas.
- **stdio only.** Streamable HTTP transport is not implemented.
- **Lexical retrieval.** TF-IDF cosine matches vocabulary, not meaning. Paraphrased queries retrieve
  poorly. Dense embeddings would be the natural upgrade; the interface would not change.
- **Deterministic compliance.** Field and regex validation only. It says nothing about whether
  extracted values are truthful.
- **Illustrative pricing.** `MODEL_PRICING` in `tools/guardrails.py` is a static table that needs
  periodic refreshing. Treat it as configuration.

## License

[MIT](LICENSE).

---
*Built by [Mishael Oliva](https://github.com/MishaelOliva) • [LinkedIn](https://www.linkedin.com/in/mishael-oliva-96a31b3a2)*
