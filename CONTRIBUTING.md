# Contributing

Thanks for your interest. This is a small reference implementation, so the bar is mostly about
honesty and correctness rather than volume.

## Getting set up

```bash
git clone https://github.com/MishaelOliva/proactive-agent-mcp.git
cd proactive-agent-mcp
python -m venv .venv
# Windows: .venv\Scripts\activate     POSIX: source .venv/bin/activate
pip install -e ".[dev]"
```

## Before opening a pull request

```bash
ruff check .
ruff format --check .
python -m unittest discover -s tests -t .
```

The suite should also pass with `MCP_SIGNING_SECRET` unset, which exercises the ephemeral-secret
path. CI checks both.

## The one rule that matters most

**Do not let a tool description, README claim, or returned metric state something the code does not
do.**

The previous release advertised "semantic vector retrieval and cosine similarity" for what was
substring matching, reported a hardcoded `4.2 ms` latency, and shipped an invented benchmark chunk
that the server then presented to models as grounded fact. A contract that overstates itself is worse
than one that admits its limits, because a reviewer or a downstream agent will rely on it.

If you approximate something, say so in the description. If a number is a measurement, measure it.
If a benchmark appears in the knowledge corpus, it had to come from somewhere real.

## Other expectations

- **New behaviour needs a test.** Prefer a test that would have caught the bug you are fixing.
  Several existing tests are named `test_regression_*` for this reason; follow that convention.
- **Security properties need explicit tests.** For the approval gate, assert the property rather
  than the implementation. See `tests/test_guardrails_security.py`.
- **Do not add a hardcoded default secret, key, or credential.** If a secret is optional, generate an
  ephemeral one and warn, as `tools/guardrails.py` does.
- **Respect the stdio contract.** Never write to stdout outside the JSON-RPC stream. Logs go to
  stderr. There is a test for this.
- **Update the README when you change public surface.** Tool names, prompt names, and environment
  variables are all documented there, and they have drifted before.

## Reporting security issues

Please follow [SECURITY.md](SECURITY.md) rather than opening a public issue.
