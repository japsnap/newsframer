# Changelog — NewsFramer

The dated, git-tracked record of what ships. Newest first. Written at `/logout`.

## 2026-06-12 (docs system restructure)
- Adopted the standard doc layout. **CLAUDE.md = orientation only**: the login/logout ritual prose was removed (now mechanized via the global SessionStart/SessionEnd hooks + `/login` `/logout` commands); the engine reference is pulled in via `@AGENTS.md`; the spec stays central at `aiautomation\spec\NewsFramer_Spec.md` (read-only).
- **BACKLOG.md** converted to the standard schema (`## Guardrails (NEVER-AUTO)` + `## Items` with `#rc`/`#ask`/`#idea` tags, size, acceptance check).
- **AGENTS.md** is now gitignored/local (privacy convention: only `CHANGELOG.md` + `README.md` are tracked; `CLAUDE.md`/`BACKLOG.md` were already local).
- Ecosystem Blueprint reference clarified as living in Obsidian; VISION pointer added.
- This `CHANGELOG.md` is new — the start of the tracked ship log.
