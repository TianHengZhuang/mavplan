# Changelog


## v1.13.0 (2026-09-22)

### Added
- **Flight replay** (`mavplan.replay_html`): single-file offline replay page — planned route vs actual track, timeline scrubber, play/pause with 1x/2x/4x rate, live altitude / speed / heading gauges, altitude-vs-distance profile with moving cursor
- CLI: `mavplan analyze replay <flight.csv> [--plan plan.json] [-o replay.html] [--fps 10]` — offline by design (no map tiles, no JS libraries); logs are down-sampled (default 1200 frames) and the page stays well under the 2 MB roadmap budget

### Fixed
- `mavplan export check`: removed a stray `output` reference left over from `export wpl`, which made `ruff` lint fail with F821

## v1.12.0 (2026-09-18)

### Added
- CLI: `mavplan export check <file>` — reload exported mission (wpl/plan/json) and fail on waypoint drift
- CLI: `mavplan grade plan` — score current mission as a plan (preflight-based rubric, schema `mavplan.grade/1` mode=plan)
- Module: `mavplan.export_check` shared by CLI and API

## v1.11.1 (2026-09-18)

### Added
- CLI: document and smoke-test `mavplan review --json` (structured three-phase review on stdout / file)
- CLI: `mavplan nfz check <mission>` — mission vs NFZ zones; `--json` schema `mavplan.nfzcheck/1`; exit code 1 on error-level hits


