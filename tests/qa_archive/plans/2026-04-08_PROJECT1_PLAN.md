# Project 1 — Real-User Boundary Test Plan
**Date:** 2026-04-08
**Target:** 210 new scenarios, 100% real-user simulation via tmux

## Principles
- Every keystroke = real user action (`tmux send-keys C-c`, `Tab`, `Up`, `BSpace`...)
- Real timing (50-200ms/key for slow typing)
- REPL restart cycles for persistence tests
- Up to 200-300 turn conversations
- NO special env vars, NO harness wrappers
- Skip cross-platform/multi-LLM (need real human/CI)

---

## Categories (210 scenarios)

| Cat | Name | Count | Priority |
|-----|------|-------|----------|
| A | Keyboard Shortcuts | 25 | P0 |
| B | Typing Simulation | 15 | P1 |
| C | Config + Restart | 30 | P0 |
| D | Long Conversations (100-300t) | 10 | P2 |
| E | Interrupt Recovery | 15 | P0 |
| F | File System Edge Cases | 30 | P1 |
| G | Anomaly Injection | 20 | P2 |
| H | Persistence Cross-Session | 15 | P1 |
| I | Terminal Environment | 10 | P2 |
| J | Command Boundaries | 30 | P0 |
| K | Concurrency / Race | 10 | P2 |

## A. Keyboard Shortcuts (25)
KB01 Ctrl+C empty | KB02 Ctrl+C streaming | KB03 Ctrl+C tool exec | KB04 Ctrl+C permission
KB05 Ctrl+D exit | KB06 Ctrl+L clear | KB07 Ctrl+O think toggle | KB08 Ctrl+E expand
KB09 Tab cmd | KB10 Tab partial | KB11 Up history | KB12 Down history
KB13 Up empty | KB14 Escape clear input | KB15 Escape close menu | KB16 BSpace
KB17 Ctrl+W del word | KB18 Ctrl+U del line | KB19 Left/Right cursor | KB20 Home/End
KB21 Esc+Enter multiline | KB22 \\ continuation | KB23 Ctrl+R | KB24 Tab path | KB25 BSpace continuous

## B. Typing Simulation (15)
TY01 100ms/key | TY02 300ms/key | TY03 20ms/key | TY04 mid-change with C-u
TY05 typo correction | TY06 mid-pause | TY07 race typing | TY08 cmd switch
TY09 paste-buffer | TY10 paste 100 lines | TY11 special chars | TY12 ANSI codes
TY13 paste Chinese | TY14 emoji block | TY15 5000-char line

## C. Config + Restart (30)
SK01-08 Custom Skills (8) | PL01-05 User Plugins (5) | HK01-05 User Hooks (5)
PR01-04 Project config (4) | OS01-04 Output Styles (4) | RU01-04 Rules persist (4)

## D. Long Conversations (10)
LC01 100t single | LC02 150t double compact | LC03 200t triple compact | LC04 300t extreme
LC05 100t+clear+100t | LC06 200t+checkpoints | LC07 mode switch | LC08 100t+50tools
LC09 100t Chinese | LC10 200t fact accumulation

## E. Interrupt Recovery (15)
IR01-15 Various Ctrl+C timings + immediate recovery actions

## F. File System (30)
FS01-10 Special filenames | SL01-05 Symlinks | DR01-08 Directory edge | FZ01-04 Sizes | PM01-03 Permissions

## G. Anomaly Injection (20)
AP01-08 API failures | FF01-06 FS failures | RS01-03 Resource exhaustion | PR01-03 Process anomalies

## H. Persistence (15)
PS01-15 save/load/resume/branch/AutoDream/vault cross-session

## I. Terminal Environment (10)
TE01-10 Different sizes/TERM/LANG combinations

## J. Command Boundaries (30)
RC01-15 Rare slash commands | AB01-15 Argument boundaries

## K. Concurrency (10)
CR01-10 Multiple REPLs / race conditions / quick send sequences

---

## Execution Order
1. **Wave 1 (P0, fast):** A + J (55 scenarios, mostly no LLM)
2. **Wave 2 (P0):** C + E (45 scenarios, restart + interrupts)
3. **Wave 3 (P1):** B + F + H (60 scenarios)
4. **Wave 4 (P2):** D + G + I + K (50 scenarios, expensive/risky)

## Rate Limit Strategy
- 8s between LLM calls
- 15s between REPL restarts
- D (long conversations) sequential only, never parallel
- G (anomaly) sequential only
- Total estimated time: ~10-15 hours
