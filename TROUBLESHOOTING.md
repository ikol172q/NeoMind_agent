# Troubleshooting Guide — user Agent

A living document of issues encountered and their fixes.
Check here first before debugging a "new" problem — it might be an old one.

---

## Environment Setup

### `ensurepip` fails when creating venv
**Symptom:** `python3 -m venv .venv` fails with ensurepip error
**Fix:** Use `python3 -m venv .venv --system-site-packages`
**Root cause:** Some macOS/Linux installs don't include ensurepip

### pip bootstrap via curl returns 403
**Symptom:** `curl https://bootstrap.pypa.io/get-pip.py` returns 403
**Fix:** Use `--system-site-packages` flag instead of bootstrapping pip
**Root cause:** Network proxy or firewall blocking the URL

### `python` command not found on macOS
**Symptom:** `python main.py` → "command not found"
**Fix:** Use `python3` — macOS doesn't alias `python` to `python3`

### pip too old for pyproject.toml editable install
**Symptom:** `pip install -e .` fails with "editable install" error
**Fix:** `pip install --upgrade pip` first, then retry

### venv points to system Python after recreation
**Symptom:** `which python3` shows `/usr/bin/python3` inside venv
**Fix:** `rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate`
**Root cause:** Stale venv symlinks after Python upgrade

---

## Terminal / Shell

### Powerlevel10k doesn't show venv marker
**Symptom:** After activating venv, p10k prompt shows no (venv) indicator
**Fix:** In `.p10k.zsh`, set `POWERLEVEL9K_VIRTUALENV_SHOW_WITH_PYENV=true`
**Root cause:** p10k hides virtualenv when pyenv is not detected by default

### `ikol` alias launches the agent instead of just activating env
**Symptom:** Typing `ikol` runs `python3 main.py` immediately
**Fix:** Alias should only `cd` + `source activate`, NOT run main.py:
```zsh
alias ikol="cd ~/Desktop/user_agent && source .venv/bin/activate"
```

---

## Git

### `git add` fails: "index.lock: File exists"
**Symptom:** `fatal: Unable to create '.git/index.lock': File exists`
**Fix:** `rm .git/index.lock`
**Root cause:** A previous git process crashed or was interrupted

### Sensitive files almost committed
**Symptom:** `.env`, `.user/`, `.venv/` show up in `git status`
**Fix:** Updated `.gitignore` with:
```
.venv/
venv/
env/
.env
.user/
run.sh
*.pem
*.key
*.secret
credentials.json
token.json
```

---

## Agent Runtime

### ModuleNotFoundError: No module named 'dotenv'
**Symptom:** `ModuleNotFoundError` on `from dotenv import load_dotenv`
**Fix:** `pip install python-dotenv` (not `dotenv` — wrong package)

### ModuleNotFoundError: No module named 'aiohttp'
**Symptom:** Import error when running agent
**Fix:** `pip install aiohttp`
**Root cause:** Was listed as optional dependency; now moved to core in pyproject.toml

### Status messages cluttering output
**Symptom:** Every request prints multiple `[INFO]` / `[DEBUG]` lines
**Fix:** Set `verbose_mode = False` by default. Use `/debug` to toggle on.
**Details:** `_status_print()` now only shows `critical` and `important` when verbose is off

### Ctrl+E keybinding doesn't work
**Symptom:** Pressing Ctrl+E does nothing or moves cursor to end of line
**Root cause:** Ctrl+E conflicts with Emacs "end of line" in prompt_toolkit
**Fix:** Removed keybinding entirely. Replaced with `/debug` command.

### Escape key eats the completion menu
**Symptom:** Pressing Escape dismisses autocomplete AND clears input
**Fix:** Added `eager=True` and check for `buf.complete_state` before clearing:
```python
@bindings.add("escape", eager=True)
def _clear_input(event):
    buf = event.current_buffer
    if buf.complete_state:
        buf.cancel_completion()
    else:
        buf.reset()
```

### Token count in status bar doesn't update
**Symptom:** Status bar shows `tokens:151` and never changes
**Fix:** Changed to use `context_manager.count_conversation_tokens()` which recalculates on each call. Display now shows `x% used/128k Nmsg`.

---

## Config System

### Hydra GlobalHydra initialization errors
**Symptom:** `GlobalHydra is already initialized` on reimport
**Fix:** Removed Hydra entirely. Replaced with plain YAML loading.
**Root cause:** Hydra uses global state that breaks on module reimport

### Config changes not reflected after mode switch
**Symptom:** Switching from chat→coding doesn't update system prompt
**Fix:** `switch_mode()` now calls `agent_config.switch_mode()` first, then reloads all settings from the new mode config

---

## Dependencies

### Hydra/OmegaConf removed
**Date:** 2026-03-14
**Why:** Hydra adds complexity (global state, config store, overrides) for simple YAML loading. Replaced with plain `PyYAML`.
**What changed:** `agent_config.py` rewritten, `pyproject.toml` updated, `agent/config.yaml` split into `agent/config/{base,chat,coding}.yaml`

---

## Architecture Decisions

### Why two separate mode configs instead of one?
Chat and coding modes have fundamentally different behaviors:
- Different system prompts (conversational vs code-focused)
- Different command sets (19 chat commands vs 37 coding commands)
- Different safety defaults (confirmations ON in chat, OFF in coding)
- Coding mode has workspace scanning, tools, permissions, auto-compact
- Mixing them in one file leads to `coding_mode.*` prefix soup

### Why no runtime mode switching?
Pick `--mode chat` or `--mode coding` at startup. Switching mid-session causes:
- System prompt confusion (conversation history has wrong context)
- Command availability confusion for the user
- Config state that's half-chat, half-coding

---

## Tool System

### For fast search, install ripgrep
**Why:** `/grep` uses ripgrep (`rg`) when available — 5-10x faster than Python regex fallback.
**Install:**
- macOS: `brew install ripgrep`
- Ubuntu/Debian: `apt install ripgrep`
- Cargo: `cargo install ripgrep`
**Note:** If `rg` is not found, `/grep` silently falls back to Python regex. It works, just slower.

### Persistent Bash session terminates after `exit`
**Symptom:** Running `exit` or `exit 1` in `/run` kills the persistent bash session
**Fix:** This is expected. The session auto-restarts on the next `/run` command.
**Root cause:** `exit` terminates the bash process; dead-process detection handles this gracefully.

### Tool output not visible to AI
**Symptom:** Run `/grep TODO` then ask "fix those" — AI doesn't know what you found
**Fix:** Tool output is now automatically added to conversation history (prefixed with `[Tool: /command]`).
**Commands that feed to AI:** /run, /grep, /find, /read, /write, /edit, /git, /code, /diff, /test, /glob, /ls, /search, /browse
**Commands that don't:** /help, /clear, /think, /debug, /save, /load, /history, /quit, /exit, /models

---

## Agentic Loop / Spinner

### RecursionError from Rich FileProxy during spinner
**Symptom:** `RecursionError: maximum recursion depth exceeded` followed by segfault when LLM starts streaming
**Root cause:** Rich's `Status` context manager replaces `sys.stdout` with a `FileProxy`. When `stream_response` calls `print()` while the proxy is still active, infinite `__getattr__` recursion occurs.
**Fix:** Replaced Rich `Status` with a lightweight ANSI spinner that writes to `sys.stderr`, completely avoiding the stdout proxy conflict.

### LLM outputs `Read "/path"` which fails as bash command
**Symptom:** `bash: line 4: read: '/path/to/file': not a valid identifier`
**Root cause:** The LLM outputs `Read "/path"` which bash interprets as the `read` builtin, not a file reader.
**Fix:** System prompt in `coding.yaml` updated to instruct: use `cat "/path/to/file"`, NOT `Read` or `read`.

### LLM hallucinating entire command chains with fake output
**Symptom:** LLM generates multiple bash blocks with inline output in one response (e.g., 13 commands with fake results). The agentic loop executes all of them against the real codebase.
**Fix:** Three-part fix:
1. `_extract_tool_blocks()` now returns only the FIRST non-hallucinated block
2. Hallucination detection: blocks followed by ` ``` ` output blocks are skipped
3. System prompt updated: "Output ONE command block, then STOP"

### Blank lines between spinner and permission prompt
**Symptom:** Two blank lines appear between `⠸ Thinking…` and `│ $ cat ...`
**Root cause:** (1) LLM outputs `\n\n` before code blocks — filter strips code but newlines pass through. (2) `print()` newline fires even when filter suppressed all content. (3) "Thought for" line had leading `\n`.
**Fix:** (1) Code fence filter strips trailing newlines before fence. (2) `content_was_displayed` flag skips trailing newline when nothing was printed. (3) Removed `\n` prefix from "Thought for" line.

---

## Multi-Provider / Model Switching

### "No answer" — model response is blank
**Symptom:** You ask a question, the spinner runs, but no text appears at the `>` prompt.
**Root cause:** Multiple possible causes (this bug was fixed through 4 rounds of debugging):
1. System prompt told model "Do NOT write explanatory prose" → model output only tool blocks → content filter suppressed everything → user saw nothing.
2. Auto-read file injection was broken — `file_content` was loaded but never appended to the prompt.
3. Agentic loop created two consecutive user messages (tool result + re-prompt), confusing the model.
**Fix:** (1) Rewrote system prompt to require plain text reasoning. (2) Fixed auto-read injection to actually append `<file>` content. (3) Combined tool result + continuation into a single user message. (4) Added `_last_content_was_displayed` fallback to show raw content when filter suppresses everything.

### DeepSeek ignores `<tool_call>` format
**Symptom:** System prompt asks for `<tool_call>` XML tags, but model outputs Python scripts with `open()` and `os.path.exists()` instead.
**Root cause:** DeepSeek models don't reliably follow structured tool call formats they weren't trained on.
**Fix:** Pivoted to bash-centric approach — system prompt now asks for ` ```bash ` blocks. Added python block fallback parser that wraps ` ```python ` blocks in `python3 << 'PYEOF'` heredocs.

### `/switch glm-5` fails with "No API key"
**Symptom:** `✗ No API key for provider 'zai'. Set ZAI_API_KEY in your .env file.`
**Fix:** Add `ZAI_API_KEY=your_key_here` to `.env`. Get your key from https://open.z.ai.

### z.ai model returns error about `thinking` parameter
**Symptom:** API error when using a GLM model with thinking mode enabled.
**Root cause:** z.ai's API doesn't support DeepSeek's `thinking` parameter.
**Fix:** Already handled — the `thinking` parameter is only sent when the provider is `deepseek`. If you see this, ensure you're on the latest `core.py`.

### Model limits feel wrong after switching
**Symptom:** Context warnings trigger too early, or responses are unexpectedly truncated.
**Root cause:** Before per-model specs, all models used the same 128K/8K limits from `base.yaml`.
**Fix:** Each model now has its own `max_context`, `max_output`, and `default_max` in `_MODEL_SPECS`. Run `/models` to see the active limits. If a model is missing from `_MODEL_SPECS`, it falls back to 128K/8K/8K defaults.

### Agentic loop hits max iterations without finishing
**Symptom:** Output ends with `(Agent loop: max iterations reached)` — model kept making exploratory tool calls without summarizing.
**Fix:** Added soft limit at iteration 8 (tells model "stop making tool calls and provide your final summary") and hard limit at 15. If you still see this, the task may be too open-ended — try breaking it into smaller requests.

### `generate_completion` hits wrong API endpoint
**Symptom:** Switched to GLM model but responses still come from DeepSeek (or get auth errors).
**Root cause:** `generate_completion` was using `self.base_url` instead of provider-resolved URL.
**Fix:** Fixed to use `provider['base_url']` from `_resolve_provider()`. If you see this, ensure you're on the latest `core.py`.

---

## Quick Diagnostics

```bash
# Check Python and venv
which python3
python3 --version
echo $VIRTUAL_ENV

# Check dependencies
pip list | grep -E "prompt_toolkit|rich|aiohttp|PyYAML|dotenv"

# Check config loads
python3 -c "from agent_config import agent_config; print(f'mode={agent_config.mode}, model={agent_config.model}')"

# Check API keys are set
python3 -c "
import os
from dotenv import load_dotenv
load_dotenv()
for key in ['DEEPSEEK_API_KEY', 'ZAI_API_KEY']:
    val = os.getenv(key, '')
    status = f'SET ({val[:8]}...)' if val else 'MISSING'
    print(f'{key}: {status}')
"

# Check provider resolution
python3 -c "
from agent.core import DeepSeekChat
for model in ['deepseek-chat', 'glm-5', 'glm-4.7-flash']:
    spec = DeepSeekChat._get_model_spec(model)
    print(f'{model}: ctx={spec[\"max_context\"]//1000}K out={spec[\"max_output\"]//1000}K default={spec[\"default_max\"]//1000}K')
"

# Run tests
python3 -m pytest tests/ -v
```
