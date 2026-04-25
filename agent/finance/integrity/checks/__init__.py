"""Individual integrity checks. Each module exposes ``check_*(conn) -> dict``
functions. The registration list lives in
``agent.finance.integrity.core._collect_checks()`` — single source of
truth for "what gets checked, and in what order".
"""
