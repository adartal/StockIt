"""Per-data-slice analyst modules.

Each analyst takes its own data bundle and a `Horizon`, calls one LLM
through the provider abstraction, and returns an `AnalystOutput`. The
prompt structure (cached system blocks + uncached user block) is
shared across analysts and locked in docs/analyst-prompt-design.md.
"""
