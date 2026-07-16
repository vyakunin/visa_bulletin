# The daily_checkup MCP server runs via `uv run` (PEP-723 inline deps), not Bazel — it
# has no build target of its own. This export exists so //tests:test_bulletin_sync_alerting
# can read it as data: it holds the daily_checkup half of the bulletin-bridge state-file
# contract, and a silent drift there costs us the ingest backstop.
exports_files(["daily_checkup_server.py"])
