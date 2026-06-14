# Changelog — NewsFramer

The dated, git-tracked record of what ships. Newest first. Written at `/logout`.

## 2026-06-14 (RC session)
- **NF-B1 verified live** — the `## 🔍 Investigations` drop-report section renders in a *delivered* brief (today's `dd781149`, sent to Telegram with 47 articles recorded). Closes NF-B1.
- **No-hardcoding enforcement test** — new `tests/test_no_hardcoding.py` fails the suite if any LLM call passes a bare `temperature`/`max_tokens`/… literal instead of a `config.get(...)` value (the most common no-hardcoding regression); includes a negative self-test so the guard can't pass hollow. Current engine code is clean.
- **dispatcher.py marked DEPRECATED + literals tidied** — added a clear DEPRECATED banner (superseded by `agents/deliver.py` + `deliver_brief.py`) and routed its HTTP timeout and inter-message pause through `config.get(key, default)`. Reference-only file; the daily crons never run it.
- **NF-E5: WhatsApp geopolitics topic filter broadened** — added rights / authoritarianism / trafficking / refugee / occupation / coup terms to the geopolitics keyword list (config-driven: live registry + committed `*.example.yaml` template + code defaults) so genuinely geopolitical stories whose analyst topics use that language are no longer dropped. The documented false-negative in `tests/test_topic_match.py` is flipped to a kept assertion.
- **Critic v1 (§10.13 / NF-F1) — standalone, not yet wired** — new `agents/critic.py` reviews a finished brief and reports issues by severity (Critical / Important / Minor): empty brief, missing citations (anti-hallucination), empty sections, character overrun vs the theme-scaled cap, thin theme count — and **never patches**. Built unwired so it cannot affect delivery until deliberately switched on between Writer and delivery. `tests/test_critic.py` (16 checks, incl. a clean-brief-passes and a never-mutates-input test). A read-only `run_critic.py` runs it over the latest stored brief for manual inspection — no send, no record.

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

## 2026-06-11 (pipeline hardening — backfilled 2026-06-14)
- **Drop-reports (§8.5)** — investigative-category articles are pulled from the normal pool and handled on a wider 7-day deduped window, rendered as a distinct `## 🔍 Investigations` section (woven into the main theme on topic match), with a short+long pair stored locally; `get_drop_report.py` returns the long form on a "more: <slug>" reply. Telegram-self path. Pure logic in `agents/drop_reports.py`, wired into `agents/writer.py`. (`2e8b566`, `b8fcc2f`)
- **Run-health watchdog (§4.5)** — `check_run_health.py` + an OpenClaw watchdog cron (06:30 JST) alert the operator over the direct Telegram Bot API (independent of OpenClaw delivery) when a stage went partial/failed, no fresh brief was produced, or the run didn't fire. (`373a18b`)
- **Per-bundle theme floors (§8.1/§8.6)** — after the unchanged clustering, theme slots are re-allocated so every active bundle (source `category`) with a qualifying article gets at least its floor of themes, no bundle exceeds its cap, and the total scales with the active-bundle count. Pure logic in `agents/bundle_floors.py`. (`d1bf14e`)
- **Hardened §4.3 delivery recording** — a brief's article IDs are recorded delivered **only after every chunk/message returns a real messageId**; on any failure, record nothing and alert. Confirmed-send seam in `agents/deliver.py`, shared by the Telegram and WhatsApp flows. (`20b606d`)
- Dates backfilled from git on 2026-06-14; all four shipped 2026-06-11.
