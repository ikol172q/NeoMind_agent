"""Investing learning library — case studies + daily fresh material.

Modules:
  persistence — DAO for learning_cases table
  seed_cases  — hand-written evergreen cases (14 to ship)
  fetcher     — pulls daily fresh material (Tavily / miniflux / RSS)
  router      — FastAPI endpoints exposed as /api/learning/*
"""
from agent.finance.learning.router import build_learning_router

__all__ = ["build_learning_router"]
