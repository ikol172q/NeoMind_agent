"""Background scanners that emit signal_events.

Each scanner is a pure-Python function that:
  - reads from raw_market_data SQLite + (sometimes) external APIs
  - emits signal_events via agent.finance.regime.signals.emit_event
  - is idempotent within its scan window (won't double-emit)
  - returns {"emitted": int, "skipped": int, "took_ms": int} for logging
"""
