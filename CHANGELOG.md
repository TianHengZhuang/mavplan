# Changelog


## v1.12.0 (2026-09-18)

### Added
- CLI: `mavplan export check <file>` — reload exported mission (wpl/plan/json) and fail on waypoint drift
- CLI: `mavplan grade plan` — score current mission as a plan (preflight-based rubric, schema `mavplan.grade/1` mode=plan)
- Module: `mavplan.export_check` shared by CLI`n
## v1.11.1 (2026-09-18)

### Added
- CLI: document and smoke-test `mavplan review --json` (structured three-phase review on stdout / file)
- CLI: `mavplan nfz check <mission>` — mission vs NFZ zones; `--json` schema `mavplan.nfzcheck/1`; exit code 1 on error-level hits


