# The daily_checkup MCP server runs via `uv run` (PEP-723 inline deps), not Bazel — it
# has no build target of its own. This export exists so //tests:test_bulletin_sync_alerting
# can read it as data: it holds the daily_checkup half of the bulletin-bridge state-file
# contract, and a silent drift there costs us the ingest backstop.
exports_files([
    "daily_checkup_server.py",
    # Read by //tests:test_mcp_pin_guard. pyproject.toml OWNS the `mcp<2` constraint
    # (the server imports `mcp.server.fastmcp`, removed in mcp 2.0.0) and uv.lock
    # records the version it actually runs on; the guard holds the PEP-723 scripts
    # that import this module to the same line.
    "pyproject.toml",
    "uv.lock",
])
