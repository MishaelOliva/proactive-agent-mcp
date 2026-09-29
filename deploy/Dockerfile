# syntax=docker/dockerfile:1
#
# Proactive Agent MCP server.
#
# The server speaks JSON-RPC over stdio, so it listens on no port. The
# EXPOSE in earlier revisions of this file was misleading and has been removed:
# an MCP host launches this process and speaks to its stdin/stdout, and nothing
# needs to reach it over the network.

FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependency layer first so source edits do not invalidate the install cache.
COPY pyproject.toml README.md ./
COPY proactive_agent_mcp ./proactive_agent_mcp

RUN pip install --upgrade pip && pip install .

COPY examples ./examples

# Drop privileges: the server needs no write access and no network.
RUN useradd --create-home --uid 1000 --shell /usr/sbin/nologin mcpuser \
    && chown -R mcpuser:mcpuser /app
USER mcpuser

# Fail the container if the server cannot import its dependencies.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import proactive_agent_mcp" || exit 1

# No EXPOSE: stdio transport binds no port.
#
# Supply MCP_SIGNING_SECRET for anything beyond local development. When it is
# unset the server generates a random ephemeral secret at start-up and warns on
# stderr, which is safe but means approval tokens do not survive a restart.
ENTRYPOINT ["python", "-m", "proactive_agent_mcp.server"]
