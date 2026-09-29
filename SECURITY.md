# Security Policy

## Scope

`proactive-agent-mcp` is a reference implementation and teaching artifact. The human-in-the-loop
approval gate and the budget guard are **worked patterns** that demonstrate the mechanics, not
production-ready controls. Please do not deploy it as a security boundary without reading
[What it does not guarantee](#what-the-approval-gate-does-not-guarantee) below.

## The approval gate: what it does

- Confirmation codes are full 256-bit HMAC-SHA256 values, base32-encoded. They are never truncated.
- The signed payload binds the ticket id, action name, a SHA-256 digest of the action parameters,
  and the absolute expiry.
- Codes are recomputed at verification time, so a tampered ticket invalidates itself.
- Tickets are single-use, verified in constant time, and garbage-collected once settled.
- `request_human_approval` never returns the confirmation code.
- There is no hardcoded default signing secret. With `MCP_SIGNING_SECRET` unset, a random secret is
  generated at start-up, so codes cannot be derived from reading the source.

## The approval gate: what it does not guarantee

- **Principal binding.** The gate proves the holder of the signing secret approved. It does not
  establish *which* human. There is no authentication, authorization, or identity on the approver.
- **Durability.** Tickets live in process memory. A restart invalidates pending tickets, and multiple
  replicas do not share them.
- **Confidential delivery.** The design assumes the confirmation code reaches the server through an
  authenticated channel the agent cannot read. Nothing in this repository implements or enforces that
  channel.
- **Isolation from privileged callers.** Anything with in-process access can read the signing secret
  and the ticket store.
- **Action-level enforcement.** The gate returns `AUTHORIZED_FOR_DISPATCH`. It does not itself
  perform or block the destructive action; the caller must honour the result.

Before relying on this pattern, add authenticated approver identity, a shared transactional ticket
store, an authenticated delivery channel, and enforcement at the point of action.

## The budget guard

Budget enforcement is real within a single process: once a session exceeds its ceiling the server
refuses non-guardrail tool calls. It is not a financial control. `MODEL_PRICING` is a static table
that drifts from real provider pricing and must be refreshed; it is not a billing source of truth.

## Reporting a vulnerability

Please report security issues privately via
[GitHub Security Advisories](https://github.com/MishaelOliva/proactive-agent-mcp/security/advisories/new)
rather than opening a public issue. Include a description, reproduction steps, and impact.

I aim to acknowledge reports within a few days. Because this is a reference implementation, the
response may be a documented limitation rather than a code change, if that is the honest answer.

## Out of scope

- Vulnerabilities in upstream dependencies (pydantic, Python itself). Report those to their
  maintainers.
- The absence of HTTP/Streamable HTTP transport.
- The in-memory storage model. It is a documented limitation, not a defect.
- Claims that this project provides production-grade authorization. It explicitly does not.
