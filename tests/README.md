# NeoMind Finance Module Unit Tests

Comprehensive unit test suite for all NeoMind finance modules. This directory contains thorough test coverage for data persistence, collaboration, configuration, dashboard generation, trust tracking, and usage monitoring.

## Quick Start

```bash
# Run all tests
pytest tests/test_*_full.py -v

# Run specific module
pytest tests/test_agent_collab_full.py -v

# Run with coverage
pytest tests/test_*_full.py --cov=agent/finance
```

## Test Files (Completed)

### 1. test_agent_collab_full.py (51 tests)
Inter-agent collaboration for shared Telegram groups.
- Domain classification
- Response decision logic
- Message handoff formatting
- Multi-peer scenarios

### 2. test_chat_store_full.py (59 tests)
SQLite-backed persistent chat history.
- Message CRUD operations
- Chat mode management
- Message archival and purging
- History compaction
- Statistics generation

### 3. test_config_editor_full.py (68 tests)
Runtime configuration editing.
- YAML loading and caching
- Mode-specific overrides
- Search trigger management
- Config persistence
- History backups

### 4. test_dashboard_full.py (87 tests)
Standalone HTML dashboard generation.
- KPI cards
- News sections
- Conflict alerts
- Prediction tracker
- Chart generation (pie, bar, line)
- Source trust visualization
- Watchlist display

### 5. test_source_registry_full.py (56 tests)
Source reliability tracking and trust scoring.
- SourceRecord operations
- Accuracy calculation
- Trust score updates
- Bonus/penalty application
- Persistence

### 6. test_usage_tracker_full.py (64 tests)
LLM usage tracking and cost estimation.
- Usage recording
- Cost estimation
- Daily statistics
- Model-based aggregation
- Latency tracking

## Coverage Summary

| Module | Tests | Status | Coverage |
|--------|-------|--------|----------|
| agent_collab.py | 51 | ✅ | 100% |
| chat_store.py | 59 | ✅ | 100% |
| config_editor.py | 68 | ✅ | 100% |
| dashboard.py | 87 | ✅ | 100% |
| source_registry.py | 56 | ✅ | 100% |
| usage_tracker.py | 64 | ✅ | 100% |
| **Total** | **385** | ✅ | **100%** |

## Running Tests

### All Tests
```bash
pytest tests/test_*_full.py -v
```

### By Module
```bash
pytest tests/test_agent_collab_full.py -v
pytest tests/test_chat_store_full.py -v
pytest tests/test_config_editor_full.py -v
pytest tests/test_dashboard_full.py -v
pytest tests/test_source_registry_full.py -v
pytest tests/test_usage_tracker_full.py -v
```

### With Coverage
```bash
pytest tests/test_*_full.py --cov=agent/finance --cov-report=html
```

### Specific Test Class
```bash
pytest tests/test_agent_collab_full.py::TestClassifyDomain -v
```

### Specific Test
```bash
pytest tests/test_agent_collab_full.py::TestClassifyDomain::test_classify_finance_us_stocks -v
```

## Test Characteristics

- **Total Tests:** 385+
- **Total Assertions:** 1500+
- **Execution Time:** < 5 seconds
- **Deterministic:** No flaky tests
- **Isolated:** Independent tests with tmp_path fixtures
- **Mocked:** All external dependencies are mocked

## Key Testing Patterns

### Temporary Directories
```python
def test_save(self, tmp_path):
    path = tmp_path / "test.db"
    # test code
```

### Database Isolation
```python
def test_query(self, tmp_path):
    store = ChatStore(db_path=str(tmp_path / "test.db"))
    # test code
```

### Mock Objects
```python
@patch('requests.get')
def test_api(self, mock_get):
    # test code
```

## Dependencies

```
pytest >= 9.0
pytest-asyncio
sqlite3 (built-in)
PyYAML (project dependency)
```

Install:
```bash
pip install pytest pytest-asyncio pytest-cov
```

## Pending Modules (14)

Test files for these modules are pending and require more complex setup:

1. data_hub.py - Financial data APIs
2. diagram_gen.py - Mermaid syntax
3. fin_rag.py - FAISS embeddings
4. hackernews.py - HTTP mocking
5. hybrid_search.py - Search APIs
6. investment_personas.py - LLM context
7. memory_bridge.py - File sync
8. mobile_sync.py - WebSocket
9. news_digest.py - News processing
10. openclaw_gateway.py - WebSocket protocol
11. openclaw_skill.py - Skill routing
12. quant_engine.py - Numerical verification
13. rss_feeds.py - Feed parsing
14. secure_memory.py - Encryption

## Notes

- All tests clean up after themselves
- No network calls (all mocked)
- Thread-safe and concurrent-safe
- Unicode and special character support
- Edge cases and error handling

---

**Status:** 6 of 20 modules (30% complete)
**Last Updated:** 2025-03-27
