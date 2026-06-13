# Changelog — NewsFramer

The dated, git-tracked record of what ships. Newest first. Written at `/logout`.

## 2026-06-13 (NF-F2 — char-overrun monitor)
- A brief that exceeds its theme-scaled character cap now **flags in the run log** (`⚠ CHAR OVERRUN: <n> chars > cap <c> (+Δ, +pct%)`) instead of passing silently — surfaces the ~15–17% editorial drift noted in spec §15. New pure helper `agents/char_monitor.py` with a config-gated tolerance (`writer_char_overrun_warn_ratio`, default `1.0` = flag any overrun; e.g. `1.15` = only flag >15% over — no hard-coding), wired into **both** brief generators: the Telegram writer (`agents/writer.py`) and the WhatsApp brief (`run_whatsapp_brief.py`, which previously logged no char count at all).
- Deliberately a **quality** flag, not a run-health failure: it does **not** touch `agent_runs.status`, so the §4.5 watchdog still treats an over-cap-but-successful brief as success (no schema change, no daily false alarms).
- Tests: `tests/test_char_monitor.py` (18 checks — over-cap flags, within-cap/tolerance silent, bad inputs never crash); full repo suite green, no regressions.

## 2026-06-12 (docs system restructure)
- Adopted the standard doc layout. **CLAUDE.md = orientation only**: the login/logout ritual prose was removed (now mechanized via the global SessionStart/SessionEnd hooks + `/login` `/logout` commands); the engine reference is pulled in via `@AGENTS.md`; the spec stays central at `aiautomation\spec\NewsFramer_Spec.md` (read-only).
- **BACKLOG.md** converted to the standard schema (`## Guardrails (NEVER-AUTO)` + `## Items` with `#rc`/`#ask`/`#idea` tags, size, acceptance check).
- **AGENTS.md** is now gitignored/local (privacy convention: only `CHANGELOG.md` + `README.md` are tracked; `CLAUDE.md`/`BACKLOG.md` were already local).
- Ecosystem Blueprint reference clarified as living in Obsidian; VISION pointer added.
- This `CHANGELOG.md` is new — the start of the tracked ship log.
