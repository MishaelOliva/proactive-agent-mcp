name: Bug report
description: Something behaves incorrectly
labels: [bug]
body:
  - type: markdown
    attributes:
      value: |
        Please do not report security vulnerabilities here. See SECURITY.md.

  - type: textarea
    id: what-happened
    attributes:
      label: What happened
      description: What did you observe, and what did you expect instead?
    validations:
      required: true

  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      description: |
        A minimal JSON-RPC exchange is ideal. Example:

        ```
        {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}
        {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"poll_event_queue","arguments":{}}}
        ```
    validations:
      required: true

  - type: input
    id: version
    attributes:
      label: Server version
      description: Output of `python -c "import proactive_agent_mcp; print(proactive_agent_mcp.__version__)"`
    validations:
      required: true

  - type: input
    id: python-version
    attributes:
      label: Python version
    validations:
      required: true

  - type: dropdown
    id: signing-secret
    attributes:
      label: Was MCP_SIGNING_SECRET set?
      description: The behaviour differs between the pinned-secret and ephemeral-secret paths.
      options:
        - "Yes"
        - "No"
    validations:
      required: true

  - type: textarea
    id: logs
    attributes:
      label: stderr output
      description: Logs go to stderr. Please paste anything relevant.
