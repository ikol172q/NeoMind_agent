# NeoMind Test Coverage Checklist

逐项核查清单 — 每个 module/function 的测试覆盖状态

## 1. agent/finance/response_validator.py
Test file: `test_response_validator_full.py`

- [ ] ValidationResult — default values
- [ ] ValidationResult.summary() — empty when passed
- [ ] ValidationResult.summary() — unverified prices
- [ ] ValidationResult.summary() — approximate calcs
- [ ] ValidationResult.summary() — unsourced data
- [ ] ValidationResult.summary() — missing time horizons
- [ ] ValidationResult.summary() — missing confidence
- [ ] ValidationResult.summary() — missing disclaimer
- [ ] ValidationResult.summary() — warnings
- [ ] ValidationResult.summary() — combined fields
- [ ] _extract_prices() — USD simple
- [ ] _extract_prices() — USD with commas
- [ ] _extract_prices() — CNY yen
- [ ] _extract_prices() — HKD
- [ ] _extract_prices() — EUR
- [ ] _extract_prices() — GBP
- [ ] _extract_prices() — currency suffix
- [ ] _extract_prices() — no prices
- [ ] _extract_prices() — multiple prices
- [ ] _extract_prices_from_tool_results() — content key
- [ ] _extract_prices_from_tool_results() — output key
- [ ] _extract_prices_from_tool_results() — empty
- [ ] _extract_prices_from_tool_results() — None content
- [ ] _extract_prices_from_tool_results() — multiple
- [ ] _normalize_price() — commas
- [ ] _normalize_price() — spaces
- [ ] _normalize_price() — already clean
- [ ] _line_has_source() — tool output marker
- [ ] _line_has_source() — known source pattern
- [ ] _line_has_source() — chinese source
- [ ] _line_has_source() — no source
- [ ] _line_has_source() — source on different line
- [ ] _line_has_source() — computed marker
- [ ] _is_in_excluded_context() — fee
- [ ] _is_in_excluded_context() — example
- [ ] _is_in_excluded_context() — chinese example
- [ ] _is_in_excluded_context() — not excluded
- [ ] FinanceResponseValidator.__init__() — default
- [ ] FinanceResponseValidator.__init__() — strict
- [ ] Rule 1 — clean response
- [ ] Rule 1 — unverified price
- [ ] Rule 1 — verified from tool
- [ ] Rule 1 — price with source marker
- [ ] Rule 1 — excluded context
- [ ] Rule 1 — strict blocks
- [ ] Rule 1 — non-strict adds disclaimer
- [ ] Rule 2 — approximate English
- [ ] Rule 2 — approximate tilde
- [ ] Rule 2 — approximate Chinese
- [ ] Rule 2 — computed OK
- [ ] Rule 2 — QuantEngine OK
- [ ] Rule 3 — unsourced price
- [ ] Rule 3 — sourced price
- [ ] Rule 3 — no prices
- [ ] Rule 4 — recommendation without time horizon
- [ ] Rule 4 — recommendation with time horizons
- [ ] Rule 4 — recommendation without confidence
- [ ] Rule 4 — recommendation with confidence
- [ ] Rule 4 — recommendation without disclaimer
- [ ] Rule 4 — English disclaimer
- [ ] Rule 4 — Chinese disclaimer
- [ ] Rule 4 — DYOR disclaimer
- [ ] Rule 4 — non-recommendation skips
- [ ] Rule 4 — _is_recommendation() detection
- [ ] Rule 5 — single source no warning
- [ ] Rule 5 — multiple sources no conflict indicator
- [ ] build_disclaimer() — unverified prices
- [ ] build_disclaimer() — approximate calcs
- [ ] build_disclaimer() — unsourced data
- [ ] build_disclaimer() — missing time horizons
- [ ] build_disclaimer() — missing confidence
- [ ] build_disclaimer() — missing disclaimer
- [ ] build_disclaimer() — bilingual
- [ ] get_finance_validator() — returns instance
- [ ] get_finance_validator() — singleton
- [ ] get_finance_validator() — strict mode
- [ ] Constants — price patterns count
- [ ] Constants — math trigger patterns
- [ ] Constants — source patterns
- [ ] Constants — recommendation keywords
- [ ] Constants — known data sources
- [ ] Constants — tool output markers
- [ ] Full flow — clean sourced response
- [ ] Full flow — mixed issues

## 2. agent/vault/watcher.py
Test file: `test_vault_watcher_full.py`

- [ ] __init__ — with vault_dir
- [ ] __init__ — stores mtimes
- [ ] __init__ — nonexistent files
- [ ] WATCHED_FILES constant
- [ ] check_for_changes() — no changes
- [ ] check_for_changes() — file modification
- [ ] check_for_changes() — new file
- [ ] check_for_changes() — file deletion
- [ ] check_for_changes() — multiple changes
- [ ] check_for_changes() — error handling
- [ ] get_changed_context() — no changes
- [ ] get_changed_context() — formatted context
- [ ] get_changed_context() — strips YAML
- [ ] get_changed_context() — section titles
- [ ] get_changed_context() — skips deleted
- [ ] get_changed_context() — all deleted
- [ ] mark_seen() — clears changes
- [ ] mark_seen() — updates mtimes
- [ ] _update_stored_mtimes() — updates
- [ ] _update_stored_mtimes() — missing file
- [ ] _update_stored_mtimes() — permission error

## 3. agent/vault/writer.py
Test file: `test_vault_writer_full.py`

- [ ] _wikify() — USD ticker
- [ ] _wikify() — multiple tickers
- [ ] _wikify() — Chinese stock code (6-digit)
- [ ] _wikify() — 000 prefix code
- [ ] _wikify() — preserves code blocks
- [ ] _wikify() — preserves existing wikilinks
- [ ] _wikify() — no lowercase wikify
- [ ] _wikify() — too long ticker
- [ ] _wikify() — ticker at EOL
- [ ] _wikify() — mixed content
- [ ] _wikify() — 5-digit not wikified
- [ ] _wikify() — 7-digit not wikified
- [ ] _wikify_learnings() — list
- [ ] _wikify_learnings() — empty
- [ ] _wikify_learnings() — preserves non-ticker
- [ ] ensure_structure() — creates dirs
- [ ] ensure_structure() — creates MEMORY.md
- [ ] ensure_structure() — creates goals
- [ ] ensure_structure() — creates SOUL.md
- [ ] ensure_structure() — creates .gitignore
- [ ] ensure_structure() — idempotent
- [ ] write_journal_entry() — creates file
- [ ] write_journal_entry() — frontmatter
- [ ] write_journal_entry() — wikifies
- [ ] write_journal_entry() — appends session
- [ ] write_journal_entry() — task status icons
- [ ] write_journal_entry() — empty tasks
- [ ] write_journal_entry() — error handling
- [ ] write_goals() — writes file
- [ ] write_goals() — empty goals
- [ ] write_goals() — frontmatter
- [ ] append_to_memory() — existing section
- [ ] append_to_memory() — new section
- [ ] append_to_memory() — deduplication
- [ ] append_to_memory() — wikifies entry
- [ ] append_to_memory() — updates count
- [ ] append_to_memory() — updates date
- [ ] write_retro() — writes file
- [ ] write_retro() — default date
- [ ] _build_frontmatter() — basic
- [ ] _build_frontmatter() — lists
- [ ] _build_frontmatter() — booleans
- [ ] _write_initial_memory() — template
- [ ] _write_initial_goals() — template
- [ ] _write_initial_soul() — template
- [ ] COMMON_WORDS — uppercase
- [ ] COMMON_WORDS — expected words
- [ ] COMMON_WORDS — count

## 4. agent/vault/promoter.py
Test file: `test_vault_promoter.py` (pre-existing)

- [x] PROMOTION_THRESHOLD == 3
- [x] Promote above threshold
- [x] Skip below threshold
- [x] Promote at exact threshold
- [x] Section map coverage
- [x] Unknown type → "Other Patterns"
- [x] Multiple patterns
- [x] Empty patterns
- [x] SharedMemory failure
- [x] Skip empty value

## 5. agent/evolution/scheduler.py
Test file: `test_evolution_scheduler_full.py`

- [ ] __init__ — stores evolve
- [ ] __init__ — default values
- [ ] check_and_run_pending() — health check
- [ ] check_and_run_pending() — returns actions
- [ ] check_and_run_pending() — health failure
- [ ] check_and_run_pending() — no evolve
- [ ] on_session_start() — health check
- [ ] on_session_start() — daily when due
- [ ] on_session_start() — skips daily
- [ ] on_session_start() — weekly when due
- [ ] on_session_start() — skips weekly
- [ ] on_session_start() — daily guard
- [ ] on_session_start() — weekly guard
- [ ] on_session_start() — health error
- [ ] on_session_start() — daily error
- [ ] on_session_start() — weekly error
- [ ] on_session_start() — no evolve
- [ ] on_turn_complete() — skips before interval
- [ ] on_turn_complete() — checks at interval
- [ ] on_turn_complete() — runs daily
- [ ] on_turn_complete() — skips if ran
- [ ] on_turn_complete() — multiple intervals
- [ ] on_turn_complete() — no evolve
- [ ] on_turn_complete() — daily error
- [ ] on_session_end() — runs daily
- [ ] on_session_end() — skips if ran
- [ ] on_session_end() — skips if not due
- [ ] on_session_end() — no evolve
- [ ] on_session_end() — error handling
- [ ] Lifecycle — full session flow
- [ ] Lifecycle — long session daily at turn

## 6. agent/evolution/dashboard.py
Test file: `test_evolution_dashboard_full.py`

- [ ] collect_metrics() — required keys
- [ ] collect_metrics() — graceful no modules
- [ ] collect_metrics() — timestamp format
- [ ] collect_metrics() — health default
- [ ] collect_metrics() — patterns default
- [ ] generate_dashboard() — returns HTML
- [ ] generate_dashboard() — contains title
- [ ] generate_dashboard() — contains Chart.js
- [ ] generate_dashboard() — health section
- [ ] generate_dashboard() — daily activity
- [ ] generate_dashboard() — mode distribution
- [ ] generate_dashboard() — patterns section
- [ ] generate_dashboard() — evidence section
- [ ] generate_dashboard() — timeline
- [ ] generate_dashboard() — learnings
- [ ] generate_dashboard() — writes to file
- [ ] generate_dashboard() — creates parent dirs
- [ ] generate_dashboard() — valid JS
- [ ] generate_dashboard() — health status green

## 7. agent/web/crawl4ai_adapter.py
Test file: `test_crawl4ai_adapter_full.py`

- [ ] __init__ — default values
- [ ] __init__ — custom values
- [ ] __init__ — no crawl4ai warning
- [ ] _normalize_url() — removes fragment
- [ ] _normalize_url() — removes trailing slash
- [ ] _normalize_url() — keeps root slash
- [ ] _normalize_url() — no changes needed
- [ ] _should_skip() — images
- [ ] _should_skip() — media
- [ ] _should_skip() — static assets
- [ ] _should_skip() — login pages
- [ ] _should_skip() — admin
- [ ] _should_skip() — ecommerce
- [ ] _should_skip() — normal pages allowed
- [ ] _should_skip() — archives
- [ ] _should_skip() — PDF
- [ ] All image extensions
- [ ] All font extensions
- [ ] Case insensitive extensions

## 8. agent/skills/loader.py
Test file: `test_skills_loader_full.py`

- [ ] Skill — default values
- [ ] Skill.to_system_prompt()
- [ ] Skill.__repr__()
- [ ] SkillLoader.__init__ — default dir
- [ ] SkillLoader.__init__ — custom dir
- [ ] SkillLoader — not loaded initially
- [ ] load_all() — loads skills
- [ ] load_all() — multiple categories
- [ ] load_all() — returns count
- [ ] load_all() — sets loaded flag
- [ ] load_all() — clears on reload
- [ ] load_all() — empty directory
- [ ] load_all() — skips non-dirs
- [ ] load_all() — skips missing SKILL.md
- [ ] get() — existing
- [ ] get() — nonexistent
- [ ] get() — auto-loads
- [ ] get_skills_for_mode() — chat
- [ ] get_skills_for_mode() — fin
- [ ] get_skills_for_mode() — coding
- [ ] get_skills_for_mode() — empty mode
- [ ] list_skills() — all
- [ ] list_skills() — by mode
- [ ] list_skills() — returns dicts
- [ ] list_skills() — sorted
- [ ] format_skill_list() — all
- [ ] format_skill_list() — by mode
- [ ] format_skill_list() — empty
- [ ] format_skill_list() — category icons
- [ ] count property
- [ ] count auto-loads
- [ ] _parse_skill_file() — with frontmatter
- [ ] _parse_skill_file() — without frontmatter
- [ ] _parse_skill_file() — string modes
- [ ] _parse_skill_file() — no modes shared
- [ ] _parse_skill_file() — no modes coding
- [ ] _split_frontmatter() — with frontmatter
- [ ] _split_frontmatter() — without
- [ ] _split_frontmatter() — incomplete
- [ ] _split_frontmatter() — empty
- [ ] get_skill_loader() — returns loader
- [ ] get_skill_loader() — singleton

## 9. agent/memory/shared_memory.py
Test file: `test_shared_memory_full.py`

- [ ] __init__ — creates DB file
- [ ] __init__ — creates parent dir
- [ ] __init__ — schema created
- [ ] __init__ — WAL mode
- [ ] set_preference() + get_preference()
- [ ] get_preference() — default
- [ ] get_preference() — None default
- [ ] set_preference() — overwrite
- [ ] get_all_preferences()
- [ ] get_all_preferences() — empty
- [ ] remember_fact() + recall_facts()
- [ ] recall_facts() — all
- [ ] recall_facts() — by category
- [ ] recall_facts() — limit
- [ ] recall_facts() — order (newest first)
- [ ] record_pattern() — new
- [ ] record_pattern() — increment
- [ ] record_pattern() — different patterns
- [ ] get_patterns() — sorted by count
- [ ] get_all_patterns()
- [ ] get_patterns() — limit
- [ ] record_feedback() + get_recent_feedback()
- [ ] feedback types
- [ ] feedback limit
- [ ] get_context_summary() — empty
- [ ] get_context_summary() — includes preferences
- [ ] get_context_summary() — includes facts
- [ ] get_context_summary() — includes patterns
- [ ] get_context_summary() — includes corrections
- [ ] get_context_summary() — mode priority
- [ ] get_context_summary() — respects budget
- [ ] clear_all()
- [ ] get_stats()
- [ ] export_json()
- [ ] import_json()
- [ ] close()
- [ ] _now() — ISO string
- [ ] _get_conn()
- [ ] _close_conn()

## 10. agent/logging/ (PIISanitizer + UnifiedLogger)
Test file: `test_logging_full.py`

### PIISanitizer
- [ ] __init__ — strict mode
- [ ] __init__ — normal mode
- [ ] sanitize() — email
- [ ] sanitize() — US phone
- [ ] sanitize() — CN phone
- [ ] sanitize() — credit card
- [ ] sanitize() — SSN
- [ ] sanitize() — API key
- [ ] sanitize() — IPv4
- [ ] sanitize() — normal mode no redaction
- [ ] sanitize() — non-string passthrough
- [ ] sanitize() — no PII
- [ ] sanitize() — multiple types
- [ ] sanitize_dict() — strings
- [ ] sanitize_dict() — nested dict
- [ ] sanitize_dict() — list values
- [ ] sanitize_dict() — non-dict input
- [ ] detect() — email
- [ ] detect() — multiple
- [ ] detect() — no PII
- [ ] detect() — non-string
- [ ] scan_message() — has PII
- [ ] scan_message() — no PII
- [ ] scan_message() — non-string
- [ ] get_stats() — counts
- [ ] get_stats() — empty

### UnifiedLogger
- [ ] __init__ — creates dir
- [ ] __init__ — has sanitizer
- [ ] log() — creates file
- [ ] log() — entry format
- [ ] log() — sanitizes PII
- [ ] log_llm_call()
- [ ] log_command()
- [ ] log_file_op()
- [ ] log_error()
- [ ] log_search()
- [ ] log_provider_switch()
- [ ] query() — today
- [ ] query() — by type
- [ ] query() — by mode
- [ ] query() — limit
- [ ] query() — date range
- [ ] query() — empty
- [ ] get_daily_stats() — today
- [ ] get_daily_stats() — empty day
- [ ] get_daily_stats() — by type
- [ ] get_daily_stats() — by mode
- [ ] get_weekly_stats()
- [ ] search() — keyword
- [ ] search() — case insensitive
- [ ] search() — limit
- [ ] search() — no results
- [ ] cleanup_old_logs() — deletes old
- [ ] cleanup_old_logs() — keeps recent
- [ ] get_all_stats()
- [ ] get_unified_logger() — singleton

---

## Test Verification Log

| Run # | Date | Tests Passed | Tests Failed | Notes |
|-------|------|-------------|-------------|-------|
| 1     |      |             |             |       |
| 2     |      |             |             |       |
| 3     |      |             |             |       |
