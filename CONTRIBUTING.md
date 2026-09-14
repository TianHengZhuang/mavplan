# Contributing to mavplan

Thanks for your interest in contributing. This project is a Python CLI/library for
MAVLink mission planning, flight-log analysis, and classroom training workflows.

## Development setup

Requirements: Python 3.10+

```bash
git clone https://github.com/TianHengZhuang/mavplan.git
cd mavplan
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Optional MAVLink extras (for `mavplan link` against a real autopilot):

```bash
pip install -e ".[mavlink]"
```

## Running tests

```bash
pytest
# with coverage
pytest --cov=mavplan --cov-report=term-missing
```

All tests should pass before you open a pull request. Aim not to decrease coverage
when adding features.

## Code style

- Target Python 3.10+ syntax and typing.
- Prefer the standard library; keep runtime dependencies minimal (currently only `click`).
- Keep the public API in `mavplan/__init__.py` intentional and documented.
- CLI help text and user-facing strings support `zh-CN` via `mavplan.i18n`; keep new
  user-facing messages translatable.

## Pull requests

1. Fork and create a topic branch from `main`.
2. Add or update tests for behavior changes.
3. Update `README.md` changelog section for user-visible changes (Keep a Changelog style).
4. Keep PRs focused — one feature or fix per PR when practical.
5. Fill in the PR template.

### Commit messages

Use clear, imperative subjects, for example:

```
fix: accept UTF-8 BOM in WPL parser
feat: add geojson export for missions
docs: clarify install extras
test: cover single-waypoint preflight
```

## Reporting bugs

Open a GitHub issue with:

- mavplan version (`mavplan --version` or `pip show mavplan`)
- Python version and OS
- Minimal command or code snippet
- Expected vs actual behavior

Security-sensitive reports: see [SECURITY.md](SECURITY.md) if present, otherwise email the maintainer.

## Feature requests

Describe the teaching or flight-planning workflow you want to enable. Link related
issues when possible. Check [docs/ROADMAP.md](docs/ROADMAP.md) first.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
