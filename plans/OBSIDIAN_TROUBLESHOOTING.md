# Obsidian Vault Integration — Troubleshooting & Self-Evolvement Guide

> **Date:** 2026-03-22
> **Status:** Active — update as issues are discovered and resolved
> **Companion docs:**
> - `2026-03-22_obsidian-vault-integration.md` — full research & rationale tracker
> - `2026-03-22_obsidian-implementation-plan.md` — implementation & test plan
>
> **Status legend:** `OPEN` = unresolved, `MITIGATED` = workaround, `RESOLVED` = fixed, `WATCH` = monitoring

---

## How To Use This Document

**For NeoMind (self-evolvement):** When the vault system encounters an error, check this document FIRST. If the issue is listed, apply the fix. If it's new, add it with severity, root cause, and fix. This document is part of NeoMind's self-improvement loop — the more failure modes documented here, the more resilient NeoMind becomes.

**For Irene:** If Obsidian or the vault behaves unexpectedly, search this doc by symptom.

---

## 1. VAULT INITIALIZATION FAILURES

### OV-001: Vault directory doesn't exist in Docker

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — verify during Phase 1 deployment |
| **Category** | Configuration |
| **Symptom** | `VaultReader.get_startup_context()` returns empty string. No vault files created. NeoMind starts without vault context. |
| **Root Cause** | Docker bind mount not configured in `docker-compose.yml`, or `~/neomind-vault` doesn't exist on Mac. |
| **Diagnosis** | Inside container: `ls -la /data/vault/`. On Mac: `ls -la ~/neomind-vault/` |
| **Fix** | 1. On Mac: `mkdir -p ~/neomind-vault` 2. In `docker-compose.yml`: add `- ~/neomind-vault:/data/vault:rw` under volumes 3. `docker compose down && docker compose up -d` |
| **Impact if unfixed** | NeoMind works normally but without vault context — no self-improvement loop. Graceful degradation, not a crash. |

### OV-002: Permission denied writing to vault from Docker

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — verify during Phase 1 |
| **Category** | Docker / Permissions |
| **Symptom** | `PermissionError: [Errno 13] Permission denied: '/data/vault/journal/2026-03-22.md'` |
| **Root Cause** | Docker container runs as a different UID than the Mac user who owns `~/neomind-vault`. Docker Desktop on macOS usually handles this transparently via VirtioFS, but edge cases exist. |
| **Diagnosis** | Inside container: `id` to check UID. `ls -la /data/vault/` to check ownership. |
| **Fix** | Option A: On Mac: `chmod -R 777 ~/neomind-vault` (quick, less secure). Option B: In Dockerfile, set `USER` to match Mac UID: `RUN useradd -u 501 neomind && USER neomind`. Option C: Use Docker named volume instead of bind mount (loses direct Mac filesystem access). |
| **Impact if unfixed** | NeoMind can read vault but not write. Self-improvement loop is half-broken (reads old data but can't update). |

### OV-003: VirtioFS `.lock` file issue (same as git HEAD.lock)

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | WATCH — recurring Docker Desktop issue |
| **Category** | Docker / VirtioFS |
| **Symptom** | Cannot delete `.git/index.lock` or `.git/HEAD.lock` from inside Docker container. Git operations in the vault fail. |
| **Root Cause** | Docker Desktop VirtioFS mount permissions prevent deleting certain files from within the VM. Known Docker Desktop limitation. |
| **Diagnosis** | `rm -f /data/vault/.git/index.lock` → "Operation not permitted" |
| **Fix** | Delete from Mac terminal: `cd ~/neomind-vault && rm -f .git/index.lock .git/HEAD.lock` |
| **Prevention** | NeoMind should NOT run git operations from inside Docker on the vault. Git operations (commit, push) should be done from the Mac side, either manually or via a cron job. |

---

## 2. VAULT READING FAILURES

### OV-010: MEMORY.md has invalid YAML frontmatter

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | MITIGATED — VaultReader strips frontmatter gracefully |
| **Category** | Data Integrity |
| **Symptom** | VaultReader returns raw YAML mixed into the context string, or returns empty string for a file that has content. |
| **Root Cause** | Manual editing of MEMORY.md in Obsidian introduced malformed YAML (missing closing `---`, special characters in values, etc.). |
| **Diagnosis** | Read the file directly: `cat /data/vault/MEMORY.md | head -10`. Check that first line is `---` and there's a matching `---` later. |
| **Fix** | Open MEMORY.md in Obsidian or text editor. Ensure frontmatter is valid YAML between `---` delimiters. Common errors: unquoted colons in values (use quotes: `title: "This: has a colon"`), tabs instead of spaces. |
| **Prevention** | VaultReader._read_file() already handles this gracefully — if frontmatter parsing fails, it returns the entire file content. |

### OV-011: Yesterday's journal doesn't exist

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | MITIGATED — by design |
| **Category** | Expected Behavior |
| **Symptom** | VaultReader doesn't inject yesterday's journal context. |
| **Root Cause** | NeoMind wasn't used yesterday, or the journal was never written (session ended abnormally). |
| **Impact** | Minimal — MEMORY.md and current-goals.md are the primary context sources. Journal is supplementary. |

### OV-012: Vault files too large for token budget

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | MITIGATED — VaultReader truncates to budget |
| **Category** | Performance |
| **Symptom** | Vault context is truncated with "[... truncated for token budget]" message. Potentially important information is cut off. |
| **Root Cause** | MEMORY.md or journal file grew very large over time. |
| **Fix** | Option A: Increase `max_tokens` parameter in `VaultReader.get_startup_context()` (default: 1500). Option B: Curate MEMORY.md — archive old entries to `learnings/` files. Option C: Prioritize recent entries by reading MEMORY.md bottom-up. |
| **Long-term fix** | Phase 5 memsearch — semantic search retrieves only relevant snippets instead of entire files. |

### OV-013: Unicode/encoding errors reading vault files

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | MITIGATED — VaultReader catches exceptions |
| **Category** | Data Integrity |
| **Symptom** | `UnicodeDecodeError` in logs. File content returns empty. |
| **Root Cause** | File saved in non-UTF-8 encoding (rare — Obsidian always saves as UTF-8). |
| **Fix** | Re-save the file in Obsidian (automatically converts to UTF-8). |

---

## 3. VAULT WRITING FAILURES

### OV-020: Journal entry not written at session end

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — must handle in implementation |
| **Category** | Data Loss |
| **Symptom** | No journal file for today despite using NeoMind. |
| **Root Cause** | Session ended abnormally (crash, SIGKILL, Docker restart) before journal write. |
| **Prevention** | Write journal incrementally throughout the session (append tasks as they complete), not just at session end. Alternative: Use `atexit` handler in Python to ensure journal is written on graceful shutdown. |
| **Fix** | Check `agent/core.py` session cleanup path. Ensure `_write_session_journal()` is called from a `try/finally` block. |

### OV-021: MEMORY.md corrupted by concurrent writes

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — design for Phase 2 |
| **Category** | Data Integrity |
| **Symptom** | MEMORY.md has garbled content, duplicate entries, or missing sections. |
| **Root Cause** | Two processes (e.g., Telegram bot + CLI) writing to MEMORY.md simultaneously. |
| **Prevention** | Use file locking (`fcntl.flock`) in VaultWriter for MEMORY.md writes. Or: only the weekly retro writes to MEMORY.md (single-writer pattern). |
| **Fix** | Restore from git: `cd ~/neomind-vault && git checkout -- MEMORY.md` |

### OV-022: Disk full — vault write fails silently

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — must handle in implementation |
| **Category** | Infrastructure |
| **Symptom** | `OSError: [Errno 28] No space left on device` |
| **Root Cause** | Mac disk full. Docker volume limit reached. |
| **Diagnosis** | On Mac: `df -h ~/neomind-vault`. In Docker: `df -h /data/vault`. |
| **Fix** | Free disk space on Mac. Archive old journal entries. |
| **Prevention** | Add disk space check to `AutoEvolve.run_startup_check()`. Warn if < 100MB free. |

---

## 4. OBSIDIAN APP ISSUES

### OV-030: Obsidian doesn't show new files written by NeoMind

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | WATCH |
| **Category** | Obsidian UI |
| **Symptom** | NeoMind wrote a journal file but it doesn't appear in Obsidian's file browser. |
| **Root Cause** | Obsidian's file watcher may not detect changes immediately from Docker bind mounts. |
| **Fix** | In Obsidian: Ctrl+P → "Reload app without saving" or close/reopen vault. Files will appear after refresh. |
| **Prevention** | This is cosmetic — Obsidian will pick up changes within a few seconds normally. |

### OV-031: Graph view shows no connections

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | OPEN — verify after Phase 3 |
| **Category** | Obsidian Feature |
| **Symptom** | Graph view shows isolated nodes with no edges. |
| **Root Cause** | NeoMind journal entries don't contain `[[wikilinks]]`. Phase 3 adds wikilinks. |
| **Fix** | Implement Phase 3 (wikilinks in journal entries). Or manually add `[[links]]` to notes. |

### OV-032: Bases view doesn't show YAML properties

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | OPEN — verify after Phase 1 |
| **Category** | Obsidian Feature |
| **Symptom** | Creating a Base from journal/ folder shows no columns or empty table. |
| **Root Cause** | Obsidian Bases requires properties (YAML frontmatter) to be present and parseable. If frontmatter has syntax errors, properties won't register. |
| **Diagnosis** | Open a journal file in Obsidian → click the Properties icon (top of note) → check if properties are displayed correctly. |
| **Fix** | Ensure YAML frontmatter uses Obsidian-compatible types: text, number, list, date. Avoid nested YAML objects. |

### OV-033: Obsidian auto-updates despite being disabled

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | WATCH |
| **Category** | Security |
| **Symptom** | Obsidian version changes despite "Automatic updates" being off. |
| **Root Cause** | Known bug reported in Obsidian forums — disabling auto-update doesn't always work. |
| **Fix** | Use macOS firewall or Little Snitch to block ALL Obsidian network connections. This prevents update downloads even if the setting is ignored. |

### OV-034: Restricted Mode accidentally disabled

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | WATCH |
| **Category** | Security |
| **Symptom** | Community plugins are running in the vault. Potential data exfiltration risk. |
| **Root Cause** | Irene accidentally toggled "Restricted mode" off, or a second vault was opened without restriction. |
| **Fix** | Settings → Community plugins → Turn ON "Restricted mode". |
| **Prevention** | Check this setting after every Obsidian update. Add to NeoMind startup health check if Obsidian REST API is ever enabled (currently not applicable). |

---

## 5. SELF-IMPROVEMENT LOOP FAILURES

### OV-040: Weekly retro doesn't generate improvement targets

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — must address in Phase 2 |
| **Category** | Self-Evolution |
| **Symptom** | `current-goals.md` is never updated after initial creation. |
| **Root Cause** | `auto_evolve.run_weekly_retro()` failed silently, or the retro's `report.improvements` list is empty because evidence trail has no entries (NeoMind wasn't used that week). |
| **Diagnosis** | Check `~/.neomind/evolution/evolution_state.json` → `last_weekly_retro` timestamp. Check evidence trail: `wc -l ~/.neomind/evidence/audit.jsonl`. |
| **Fix** | If evidence trail is empty: expected behavior — no data means no retro. If retro ran but improvements empty: enhance `_generate_improvements()` to always produce at least 1 target based on available data. |

### OV-041: Pattern promoted to MEMORY.md is wrong

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | MITIGATED — human-in-the-loop |
| **Category** | Self-Evolution |
| **Symptom** | MEMORY.md contains a factually incorrect pattern (e.g., "User prefers Python" when user prefers Rust). |
| **Root Cause** | Pattern was observed 3+ times but the observations were in error (NeoMind misinterpreted conversations). |
| **Fix** | Open MEMORY.md in Obsidian. Delete the incorrect line. Save. NeoMind reads corrected version at next startup. |
| **Prevention** | This is by design — the 3-occurrence threshold reduces but doesn't eliminate false patterns. Human editing of MEMORY.md is the safety valve. Consider raising threshold to 5 if false patterns are frequent. |

### OV-042: MEMORY.md grows unbounded

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN — address after 3 months of usage |
| **Category** | Scalability |
| **Symptom** | MEMORY.md exceeds 10KB. VaultReader truncates it at startup. Important recent knowledge is cut off. |
| **Root Cause** | Promoter appends entries but never removes old ones. |
| **Fix** | Manual curation: Irene reviews MEMORY.md quarterly, archives old entries to `learnings/` files. OR: implement auto-archival — move entries older than 90 days to `learnings/archive-{year}.md`. |
| **Long-term fix** | Phase 5 memsearch — semantic search over full vault replaces need for a single curated file. |

### OV-043: Goals stale — same targets repeated weekly

| Field | Value |
|-------|-------|
| **Severity** | LOW |
| **Status** | WATCH |
| **Category** | Self-Evolution |
| **Symptom** | `current-goals.md` contains the same 3 goals for multiple weeks. No progress. |
| **Root Cause** | Retro generates goals but NeoMind doesn't measure progress against them. The retro compares against last week's evidence trail but may not have enough data to detect improvement. |
| **Fix** | Enhance retro to compare current metrics against goal targets. If a goal's metric hasn't improved in 2 weeks, replace it with a new goal. Track goal history in `retros/` for trend analysis. |

---

## 6. SECURITY INCIDENTS

### OV-050: Obsidian plugin installed by accident

| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Status** | N/A — preventive |
| **Category** | Security |
| **Response** | 1. Immediately enable Restricted Mode: Settings → Community plugins → ON. 2. Delete the plugin folder: `rm -rf ~/neomind-vault/.obsidian/plugins/<plugin-name>`. 3. Review recent vault changes: `cd ~/neomind-vault && git diff`. 4. If suspicious changes found, revert: `git checkout -- .`. 5. Block Obsidian network if not already done. |

### OV-051: Suspicious file appears in vault

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | N/A — preventive |
| **Category** | Security |
| **Response** | 1. Do NOT open the file in Obsidian (CVE-2023-2110 requires opening a malicious file). 2. Check git: `cd ~/neomind-vault && git status` — if the file is untracked and NeoMind didn't create it, investigate. 3. Delete: `rm ~/neomind-vault/<suspicious-file>`. 4. Audit NeoMind logs for unexpected file creation. |

### OV-052: Vault exposed to network share or cloud sync

| Field | Value |
|-------|-------|
| **Severity** | CRITICAL |
| **Status** | N/A — preventive |
| **Category** | Security |
| **Response** | 1. Immediately stop any cloud sync (iCloud, Dropbox, Google Drive) for `~/neomind-vault`. 2. Verify: `ls -la ~/neomind-vault` — no `.icloud`, `.dropbox`, or similar metadata folders. 3. macOS: System Settings → iCloud Drive → ensure neomind-vault is excluded. 4. Check `.gitignore` contains `.obsidian/` to prevent syncing Obsidian config. |

---

## 7. DOCKER & INFRASTRUCTURE

### OV-060: Docker bind mount path doesn't match

| Field | Value |
|-------|-------|
| **Severity** | HIGH |
| **Status** | OPEN — verify during deployment |
| **Category** | Configuration |
| **Symptom** | `VaultReader` reads from `/data/vault` inside Docker but the directory is empty. |
| **Root Cause** | `docker-compose.yml` mount path doesn't match. E.g., `~/neomind-vault` on Mac but `/data/vault` expected in container. |
| **Diagnosis** | `docker compose exec neomind ls -la /data/vault/` |
| **Fix** | Ensure docker-compose.yml has: `- ~/neomind-vault:/data/vault:rw` |

### OV-061: NEOMIND_VAULT_DIR env var conflicts

| Field | Value |
|-------|-------|
| **Severity** | MEDIUM |
| **Status** | OPEN |
| **Category** | Configuration |
| **Symptom** | VaultReader looks in wrong directory. Journal files appear in unexpected location. |
| **Root Cause** | `NEOMIND_VAULT_DIR` environment variable set to a non-standard path. |
| **Diagnosis** | `echo $NEOMIND_VAULT_DIR` inside container. |
| **Fix** | Either unset the env var (use defaults) or update to correct path in `.env` or docker-compose.yml. |

---

## 8. SELF-EVOLVEMENT CHECKLIST

When NeoMind encounters a new vault-related issue:

1. **Check this document first** — search by symptom or error message
2. **If issue is known** — apply the documented fix
3. **If issue is NEW** — add it to this document following the template:

```markdown
### OV-XXX: [Short description]

| Field | Value |
|-------|-------|
| **Severity** | CRITICAL / HIGH / MEDIUM / LOW |
| **Status** | OPEN / MITIGATED / RESOLVED / WATCH |
| **Category** | [Category] |
| **Symptom** | [What the user or NeoMind observes] |
| **Root Cause** | [Why it happens] |
| **Diagnosis** | [Commands or checks to confirm] |
| **Fix** | [Step-by-step resolution] |
| **Prevention** | [How to avoid in future] |
```

4. **Update the companion tracker** if the issue reveals a gap in the architecture
5. **Log the resolution** in the evidence trail for the weekly retro to analyze

---

## VERSION HISTORY

| Date | Change | Author |
|------|--------|--------|
| 2026-03-22 | Initial creation with 25 documented failure modes | NeoMind |
