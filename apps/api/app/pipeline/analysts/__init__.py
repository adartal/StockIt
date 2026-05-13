"""Per-domain analysts that turn fetched data into `AnalystOutput`.

Each analyst is one LLM call constructed from the shared prompt template
described in docs/analyst-prompt-design.md. The four analysts
(fundamentals, technicals, news, macro) run in parallel from the M5
orchestrator and produce structured JSON consumed by the M5 synthesizer.
"""
