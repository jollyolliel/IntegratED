"""Teacher AI assistant.

Layout:
  provider.py  neutral LLM interface + transcript types (no vendor names)
  gemini.py    the one Gemini implementation
  registry.py  get_provider() — the single swap point
  scope.py     FK-graph walk deriving "rows this teacher may see" per model
  tools/       @ai_tool registry: auto-derived reads, curated analysis + writes
  loop.py      agent loop, streams step/delta events
"""
