# CLAUDE.md

## Branching and commits

- **Always create a new branch** before making any changes. Never commit directly to `main`.
- **Never push `main`** to the remote.
- **Never amend commits** (`git commit --amend`). If a fix is needed after a commit, create a new commit.

---

## Project overview

**openscad-toolkit** is a Python build-tool suite for OpenSCAD projects. The core feature is a compiler that recursively inlines `use`/`include` dependencies into a single self-contained `.scad` file — suitable for publishing to platforms like MakerWorld and Printables.

- `use <file>` — inlines only module/function definitions (variables hidden from Customizer)
- `include <file>` — inlines all content
- External library references (e.g. `BOSL2/`) are preserved at the top of output
- Supports OpenSCAD Customizer comments and watch-mode auto-recompile

---

## Tech stack

| | |
|---|---|
| Language | Python 3.10+ |
| Build system | setuptools + setuptools-scm (version from git tags) |
| Dev tools | pytest, ruff, mypy |
| Optional | watchdog (watch mode) |
| Runtime deps | none |

---

## Project structure

```
src/scadtools/
  __init__.py       public API exports, version detection
  cli.py            argparse CLI entry point
  compiler.py       core compiler (main logic)
  watch.py          watch-mode (watchdog-based)
tests/
  test_compiler.py  unit + integration tests for compiler
  test_cli.py       CLI integration tests (subprocess-based)
  test_stl_render.py
  fixtures/         .scad test files
.github/workflows/
  ci.yml            lint, type-check, test matrix (3.10-3.13)
  auto-tag.yml      auto-bump minor version on src/ changes
  release.yml       build wheel + Docker image on tag push
```

---

## Development commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Test
pytest

# Lint
ruff check src/ tests/

# Format (auto-fix)
ruff format src/ tests/

# Format check only (what CI runs)
ruff format --check src/ tests/

# Type check
mypy src/scadtools/
```

> **Important:** CI runs both `ruff check` *and* `ruff format --check`. Always run `ruff format src/ tests/` before committing or the Lint job will fail.

---

## CI checks (must all pass before merge)

1. **Lint** — `ruff check` + `ruff format --check` (Python 3.12)
2. **Type check** — `mypy src/scadtools/` (Python 3.12)
3. **Tests** — `pytest` on Python 3.10, 3.11, 3.12, 3.13

---

## Coding conventions

- Functions/variables: `snake_case`; module-level constants: `SCREAMING_SNAKE_CASE`
- Full type annotations throughout; union types with `|` (Python 3.10+)
- Regex patterns pre-compiled as module-level constants (`INCLUDE_RE`, `MODULE_START_RE`, etc.)
- Output built by list accumulation, joined at the end
- State-machine parsing for multi-line constructs (braces, assignments, block comments)
- Line length: 130 (ruff `line-length`)
