# Nancy visual board

The visual board is a read-only presentation surface beside Nancy's chat. Board
documents are schema-validated, persisted in the existing SQLite database and
delivered to connected browsers through authenticated server-sent events.

## Hermes configuration

Install the updated Python dependencies, then add the server and repository skill
directory to `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  nancy_board:
    command: "/opt/hermes-control/.venv/bin/python"
    args: ["-m", "nancy_mcp.board_server"]
    env:
      PYTHONPATH: "/opt/hermes-control"
      HISTORY_DB_PATH: "/var/lib/hermes-control/history.db"
    timeout: 120
    connect_timeout: 60

skills:
  external_dirs:
    - /opt/hermes-control/skills
```

Restart the Hermes gateway after changing its configuration. Hermes discovers the
tools as:

- `mcp_nancy_board_show_board`
- `mcp_nancy_board_update_component`
- `mcp_nancy_board_remove_component`
- `mcp_nancy_board_clear_board`

The MCP server uses stdio. Its stdout is reserved for MCP protocol traffic.

## HTTP API

- `GET /board?conversation=voice-main` returns the current board.
- `PUT /board` validates and replaces a board.
- `DELETE /board?conversation=voice-main` clears it.
- `GET /board/events?conversation=voice-main&after=0` streams updates.

All endpoints use the existing control-key bearer authentication. The browser uses
authenticated `fetch()` streaming rather than native `EventSource`, because native
`EventSource` cannot attach the Authorization header.

## Safety boundary

Components are a closed Pydantic discriminated union. Unknown types and extra
fields are rejected. The browser builds DOM nodes with `textContent`; it never
renders agent-provided HTML or JavaScript. The board contains no source-system
actions or editing controls.
