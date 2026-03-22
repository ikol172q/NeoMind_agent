# gstack Integration Troubleshooting

## P0: Skill System

| Issue | Cause | Fix |
|-------|-------|-----|
| SKILL.md not found | Wrong path in skill registry | Check `agent/skills/` directory structure |
| Frontmatter parse error | Invalid YAML in SKILL.md header | Validate with `python -c "import yaml; yaml.safe_load(open('SKILL.md'))"` |
| Skill not available in mode | Not listed in mode's skill config | Add to `agent/config/{mode}.yaml` skills list |
| Skill loads but does nothing | Body prompt not injected into LLM context | Check `loader.py` injects skill body into system prompt |

## P1: Browser Daemon

| Issue | Cause | Fix |
|-------|-------|-----|
| Playwright not installed | Missing in Docker image | Add `playwright install chromium` to Dockerfile |
| Chromium won't start in Docker | Missing system deps | Add `playwright install-deps` to Dockerfile |
| Browser daemon port conflict | Another process on the port | Use random port (10000-60000 range) like gstack |
| "Connection refused" from agent | Daemon not running or wrong port | Check `~/.neomind/browser.json` for PID/port, restart daemon |
| Slow first command (~3s) | Chromium cold start | Expected — subsequent commands are ~100ms |
| Screenshots blank | Headless rendering issue | Try `--disable-gpu` flag, check viewport size |
| Cannot login to sites | No cookies | Use `/setup-cookies` to import from host browser |
| CORS/CSP blocks | Site security policies | Use snapshot refs (no DOM injection), not direct JS |

## P2: Safety Guards

| Issue | Cause | Fix |
|-------|-------|-----|
| /careful not triggering | Command not in destructive list | Add pattern to `guards.py` DANGEROUS_PATTERNS |
| /freeze blocks wrong directory | Freeze path not set correctly | Check `/freeze` state in `~/.neomind/freeze.json` |
| /guard too aggressive | Blocks legitimate operations | Use `/unfreeze` or adjust guard rules |
| Safety bypass needed | Emergency situation | Use `/unfreeze` then re-enable after |

## P3: Sprint Framework

| Issue | Cause | Fix |
|-------|-------|-----|
| Sprint stuck on one phase | LLM not advancing to next phase | Check sprint state file, manually advance with `/sprint next` |
| Context too large for sprint | Full sprint prompt + history exceeds context | Auto-compact triggers, or use `/clear` between phases |
| Design doc not propagating | File not saved to expected path | Check `DESIGN.md` / `PLAN.md` path conventions |

## P4: Review + Evidence

| Issue | Cause | Fix |
|-------|-------|-----|
| Evidence screenshots missing | Browser daemon not running | Start daemon first, or review falls back to text-only |
| Review finds false positives | LLM hallucinating issues | Add "verify with actual code" instruction to review prompt |
| Audit trail too large | Too many screenshots | Set max evidence per review (default: 10 screenshots) |

## P5-P7: Mode-Specific Skills

### Coding Mode

| Issue | Cause | Fix |
|-------|-------|-----|
| /qa can't access localhost | Docker networking | Use `host.docker.internal` or expose port |
| /ship pushes to wrong branch | Git state mismatch | Check `git status` and `git branch` before /ship |
| /eng-review too slow | Full codebase scan | Scope review to changed files only (`git diff`) |

### Finance Mode

| Issue | Cause | Fix |
|-------|-------|-----|
| /trade-review blocks valid trade | Risk limits too tight | Adjust limits in `fin.yaml` finance settings |
| /finance-briefing no data | API keys not set | Check FINNHUB_API_KEY, data_hub fallback chain |
| /qa-trading paper trade fails | Broker API down | Retry or skip paper test with explicit confirmation |

### Chat Mode

| Issue | Cause | Fix |
|-------|-------|-----|
| /office-hours too aggressive | Asks too many questions | User can skip questions with "pass" |
| Forcing questions not relevant | Generic prompts | Mode-aware: finance questions for fin, code questions for coding |

## General

| Issue | Cause | Fix |
|-------|-------|-----|
| Import error on skill module | Missing dependency | Check `pyproject.toml` optional deps for the skill |
| Skill works in CLI but not Telegram | Telegram bot doesn't load skill | Check `telegram_bot.py` skill routing |
| Tests fail after integration | New module breaks imports | Run `pytest tests/` to isolate failing test |
| Docker build fails | New deps not in Dockerfile | Add to `pip install` line in Dockerfile |
