"""Optional third-party brokerage / financial-data integrations.

Each integration is self-contained, gracefully degrades when its
credentials are missing, and never imports its concrete deps at top
level (so the dashboard boots even without optional libs installed).
"""
