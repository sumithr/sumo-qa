# OSS-readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land everything needed to make sumo-qa public-ready: Apache 2.0 license with attribution-preserving NOTICE file, all pre-existing untracked install/Docker files committed, three GitHub Actions workflows (test matrix + lint + release-to-PyPI), Dependabot config, and a public-facing README polish pass.

**Architecture:** Five mostly-independent task groups. Tasks 1, 2, 3 touch disjoint files and can be dispatched in parallel. Task 4 (README) depends on Tasks 1 + 3 having landed (it references the new license + the new workflow filenames in badges). Task 5 is a final verification pass.

**Tech Stack:** Python 3.10-3.13, hatchling build, pytest, ruff (new), uv tool, GitHub Actions, Apache 2.0 license.

**Spec:** [`docs/superpowers/specs/2026-05-12-oss-readiness-design.md`](../specs/2026-05-12-oss-readiness-design.md)

---

## File Structure

**Created:**
- `LICENSE` — Apache 2.0 text (verbatim, ~11KB)
- `NOTICE` — 3-line attribution-preservation block
- `ruff.toml` — minimal lint config
- `.github/workflows/test.yml` — test matrix (Python × OS)
- `.github/workflows/lint.yml` — ruff check + format check
- `.github/workflows/release.yml` — build + publish to PyPI on tag (OIDC trusted publishing)
- `.github/dependabot.yml` — weekly pip + github-actions update PRs

**Modified:**
- `pyproject.toml` — license SPDX, authors, urls, ruff in dev extras
- `.claude-plugin/plugin.json` — license MIT → Apache-2.0
- `.claude-plugin/marketplace.json` — license MIT → Apache-2.0
- `.cursor-plugin/plugin.json` — license MIT → Apache-2.0
- `.codex-plugin/plugin.json` — license MIT → Apache-2.0
- `README.md` — badges, "Why sumo-qa?" section, install reordering, license footer, remove status line
- `docs/ARCHITECTURE.md` — note Apache 2.0 in standard footer

**First-time committed (currently untracked):**
- `install.sh`
- `Dockerfile`
- `.dockerignore`
- `uv.lock`
- `standards/packs/istqb_v1.yml`
- `standards/packs/qa_shift_left_v1.yml`

**Stays untracked (gitignored, JL-local fixtures):**
- `knowledge/test_data/fulfilment/`
- `knowledge/test_data/stock/`

---

## Task 1: License + attribution mechanics

**Files:**
- Create: `LICENSE`
- Create: `NOTICE`
- Modify: `pyproject.toml`
- Modify: `.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `.cursor-plugin/plugin.json`
- Modify: `.codex-plugin/plugin.json`
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Download the Apache 2.0 LICENSE text**

```bash
curl -sSL https://www.apache.org/licenses/LICENSE-2.0.txt -o LICENSE
wc -l LICENSE
```
Expected: ~202 lines.

- [ ] **Step 2: Write NOTICE file**

Content (3 lines exactly):
```
sumo-qa
Copyright 2026 Sumith Ramsookbhai
Licensed under the Apache License, Version 2.0.
```

- [ ] **Step 3: Update pyproject.toml — license, authors, urls**

Find the existing `[project]` section. Replace the `description` block:

Currently:
```toml
[project]
name = "sumo-qa"
version = "0.1.0"
description = "Sumo QA — a senior-QA-shaped MCP server for shift-left testing, mutation-testing follow-up, code review, and test-data discovery."
readme = "README.md"
```

Change to:
```toml
[project]
name = "sumo-qa"
version = "0.1.0"
description = "Sumo QA — a senior-QA-shaped MCP server for shift-left testing, mutation-testing follow-up, code review, and test-data discovery."
readme = "README.md"
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
authors = [{ name = "Sumith Ramsookbhai" }]
```

Then locate `[project.scripts]` and insert these blocks BEFORE it:
```toml
[project.urls]
Homepage = "https://github.com/SumithRamsookbhai/qa-shift-left-mcp"
Repository = "https://github.com/SumithRamsookbhai/qa-shift-left-mcp"
Issues = "https://github.com/SumithRamsookbhai/qa-shift-left-mcp/issues"
```

- [ ] **Step 4: Update `.claude-plugin/plugin.json` license**

Change the `"license": "MIT"` line to `"license": "Apache-2.0"`.

- [ ] **Step 5: Update `.claude-plugin/marketplace.json` license**

If the file contains `"license":` keys, change values from `"MIT"` to `"Apache-2.0"`. If no license key exists at the marketplace or plugin level, skip — marketplace.json doesn't always carry one.

- [ ] **Step 6: Update `.cursor-plugin/plugin.json` license**

Change the `"license": "MIT"` line to `"license": "Apache-2.0"`.

- [ ] **Step 7: Update `.codex-plugin/plugin.json` license**

Change the `"license": "MIT"` line to `"license": "Apache-2.0"`.

- [ ] **Step 8: Update `docs/ARCHITECTURE.md`**

If a "License" / footer section exists, update the licence mention. If no such section exists, append at the very bottom:

```markdown

---

Licensed under the Apache License 2.0. See [LICENSE](../LICENSE) and [NOTICE](../NOTICE) at the repo root.
```

- [ ] **Step 9: Verify build still works**

```bash
uv build 2>&1 | tail -20
```
Expected: builds `sumo_qa-0.1.0-py3-none-any.whl` and `sumo_qa-0.1.0.tar.gz` in `dist/` without warnings about the license field. The `license-files = [...]` array must resolve.

- [ ] **Step 10: Verify tests still pass**

```bash
uv run pytest --tb=short -q
```
Expected: `169 passed, 1 xfailed`.

- [ ] **Step 11: Commit**

```bash
git add LICENSE NOTICE pyproject.toml .claude-plugin/plugin.json .claude-plugin/marketplace.json .cursor-plugin/plugin.json .codex-plugin/plugin.json docs/ARCHITECTURE.md
git commit -m "docs(license): adopt Apache 2.0 + add LICENSE + NOTICE

Apache 2.0 chosen for its NOTICE-file attribution-preservation
mechanic — forks and redistributors MUST preserve NOTICE content,
which MIT does not require for derivative output. Adds the SPDX
identifier to pyproject + all 4 plugin manifests so the license
metadata is consistent everywhere a host reads it."
```

---

## Task 2: Commit pre-existing untracked files

**Files (first-time commit):**
- `install.sh`
- `Dockerfile`
- `.dockerignore`
- `uv.lock`
- `standards/packs/istqb_v1.yml`
- `standards/packs/qa_shift_left_v1.yml`

These already exist on disk and are load-bearing for public install. They've been sitting untracked since earlier development.

- [ ] **Step 1: Sanity-check `install.sh` runs the documented one-line install**

```bash
head -3 install.sh
```
Expected: `#!/usr/bin/env bash` shebang + descriptive comment about being the one-command installer.

```bash
shellcheck install.sh 2>&1 | head -10 || echo "shellcheck not installed — skipping; CI will lint via shellcheck-action"
```

- [ ] **Step 2: Sanity-check `Dockerfile` references the current Python version supported**

```bash
head -1 Dockerfile
```
Expected: `FROM python:3.12-slim` (or similar in the 3.10–3.13 range that matches pyproject's `requires-python`).

- [ ] **Step 3: Sanity-check `.dockerignore` excludes the right things**

```bash
cat .dockerignore
```
Expected: at minimum `.git`, `.venv`, `__pycache__`, `*.py[cod]`, `.pytest_cache`. The list is fine if it includes those.

- [ ] **Step 4: Sanity-check `uv.lock` matches current pyproject**

```bash
uv lock --check 2>&1 | tail -5
```
Expected: `The lockfile is up to date.` If not up-to-date, run `uv lock` first.

- [ ] **Step 5: Scan standards/packs for internal references**

```bash
grep -iE "john.?lewis|waitrose|jlp|partnership|byvariant|johnlewis" standards/packs/ -r && echo "STOP — internal references found" || echo "clean"
```
Expected: `clean`.

- [ ] **Step 6: Commit**

```bash
git add install.sh Dockerfile .dockerignore uv.lock standards/packs/
git commit -m "chore: commit install.sh + Dockerfile + uv.lock + standards/packs

These have existed on disk but stayed untracked through earlier
work. They're load-bearing for public install (install.sh is the
one-line bash entry point; Dockerfile is the container path;
uv.lock pins deps for reproducible CI builds; standards/packs
ships the ISTQB-aligned + shift-left baseline packs the MCP
loads at startup)."
```

---

## Task 3: CI workflows + Dependabot + ruff

**Files:**
- Create: `.github/workflows/test.yml`
- Create: `.github/workflows/lint.yml`
- Create: `.github/workflows/release.yml`
- Create: `.github/dependabot.yml`
- Create: `ruff.toml`
- Modify: `pyproject.toml` (add ruff to dev extras)

- [ ] **Step 1: Add ruff to dev extras in pyproject.toml**

Find the existing `[project.optional-dependencies]` block:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.4,<9",
  "pytest-cov>=6,<7",
]
```

Replace with:

```toml
[project.optional-dependencies]
dev = [
  "pytest>=8.4,<9",
  "pytest-cov>=6,<7",
  "ruff>=0.5,<1",
]
```

- [ ] **Step 2: Create `ruff.toml`**

```toml
line-length = 100
target-version = "py310"

[lint]
select = ["E", "F", "I", "B", "UP"]
ignore = ["E501"]  # line-length handled by formatter

[format]
quote-style = "double"
```

- [ ] **Step 3: Sync uv to pick up ruff**

```bash
uv sync --all-extras
```
Expected: installs ruff alongside existing deps.

- [ ] **Step 4: Run ruff locally to see current state**

```bash
uv run ruff check . 2>&1 | tail -20
uv run ruff format --check . 2>&1 | tail -5
```
If either reports issues: fix them (`uv run ruff check --fix .` and `uv run ruff format .`), then re-run to confirm clean. Commit any fixes as part of Step 12 below.

- [ ] **Step 5: Create `.github/workflows/test.yml`**

```yaml
name: tests

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  test:
    name: pytest (${{ matrix.os }} · py${{ matrix.python-version }})
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install ${{ matrix.python-version }}

      - name: Sync dependencies
        run: uv sync --all-extras --python ${{ matrix.python-version }}

      - name: Run pytest
        run: uv run --python ${{ matrix.python-version }} pytest -q
```

- [ ] **Step 6: Create `.github/workflows/lint.yml`**

```yaml
name: lint

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main]

jobs:
  ruff:
    name: ruff check + format
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Sync dependencies
        run: uv sync --all-extras

      - name: ruff check
        run: uv run ruff check .

      - name: ruff format --check
        run: uv run ruff format --check .
```

- [ ] **Step 7: Create `.github/workflows/release.yml`**

```yaml
name: release

on:
  push:
    tags:
      - "v*"

jobs:
  build:
    name: Build wheel + sdist
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Build
        run: uv build

      - name: Upload artefacts
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    name: Publish to PyPI
    needs: build
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write  # OIDC trusted publishing
    steps:
      - name: Download artefacts
        uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 8: Create `.github/dependabot.yml`**

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "08:00"
      timezone: Europe/London
    open-pull-requests-limit: 5
    labels: ["deps"]

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
      day: monday
      time: "08:00"
      timezone: Europe/London
    open-pull-requests-limit: 5
    labels: ["deps", "ci"]
```

- [ ] **Step 9: Verify YAML syntactically valid**

```bash
python3 -c "import yaml; [yaml.safe_load(open(p)) for p in ['.github/workflows/test.yml','.github/workflows/lint.yml','.github/workflows/release.yml','.github/dependabot.yml']]; print('all 4 valid')"
```
Expected: `all 4 valid`.

- [ ] **Step 10: Verify ruff still passes after adding workflow YAML**

```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: both clean.

- [ ] **Step 11: Verify pytest still passes**

```bash
uv run pytest -q
```
Expected: `169 passed, 1 xfailed`.

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml ruff.toml .github/workflows/test.yml .github/workflows/lint.yml .github/workflows/release.yml .github/dependabot.yml
git commit -m "ci: test + lint + release workflows + dependabot + ruff config

test.yml: pytest matrix across Python 3.10-3.13 × ubuntu/macos.
lint.yml: ruff check + ruff format check.
release.yml: builds wheel + sdist on v* tag, publishes via PyPI
  trusted publishing (OIDC, no secrets).
dependabot.yml: weekly pip + github-actions update PRs.

Adds ruff to dev extras + minimal ruff.toml (line-length 100,
default E/F/I/B/UP rules)."
```

If Step 4 produced any auto-fixes, add them in the same commit (use `git add -p` to include only the fix changes, or just `git add -A` if nothing else is dirty).

---

## Task 4: README polish + DEPENDS ON Tasks 1 + 3

> **Sequence:** Run this task only AFTER Tasks 1 and 3 have been committed (badges reference the workflow names from Task 3; the License section references the file from Task 1).

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read current README to know what's there**

```bash
cat README.md
```
Note the current section order so the rewrite preserves what works.

- [ ] **Step 2: Add badges at the very top of README.md**

Insert these lines immediately AFTER the H1 `# sumo-qa MCP` line (line 1) and BEFORE the existing tagline paragraph:

```markdown
[![tests](https://github.com/SumithRamsookbhai/qa-shift-left-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/SumithRamsookbhai/qa-shift-left-mcp/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/sumo-qa.svg)](https://pypi.org/project/sumo-qa/)
[![Python](https://img.shields.io/pypi/pyversions/sumo-qa.svg)](https://pypi.org/project/sumo-qa/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

```

(Blank line at the end is required so it doesn't visually fuse with the tagline.)

- [ ] **Step 3: Insert "Why sumo-qa?" section after the tagline, BEFORE "Setup"**

Find the existing `## Setup` heading. Immediately BEFORE it, insert:

```markdown
## Why sumo-qa?

Most AI coding assistants approach QA the way a junior engineer would: *"add unit tests, consider edge cases, maybe test performance too."* That's a checklist, not testing. sumo-qa makes the AI work like a senior QA — risks named against specific lines, design techniques (boundary-value, decision-table, property-based, mutation) picked from a loaded ISTQB-grounded catalogue, test suites run fresh in *this* turn before any "safe to merge" claim.

The discipline is enforced by [13 skill files](skills/) the host LLM follows literally — each one with an Iron Law (TDD's red phase before any production code; mutation-strengthening keeps production code locked; no plan ships without measurable entry AND exit criteria) and a HARD-GATE callout the LLM can't talk itself past. A SessionStart hook auto-injects the entry router on every conversation, so the workflow kicks in without you having to remember to invoke it.

Read [DEMO.md](DEMO.md) for the 5-minute install-and-run-this-prompt walkthrough.

```

- [ ] **Step 4: Replace the "Setup" section header + reorder install paths**

Find the current `## Setup` section. Replace it (and the "Easy path" / "Multi-host path" subsections that follow) with the new ordering below. Keep the same install commands; the change is ORDER and the addition of the PyPI path.

```markdown
## Install

### One-line install (PyPI)

```bash
pip install sumo-qa
# or:  uv tool install sumo-qa
```

After install, restart your MCP host (Claude Code / Cursor / Codex / OpenCode / JetBrains AI Assistant / VS Code + Copilot) so it picks up the new MCP server.

### Claude Code plugin

```text
/plugin marketplace add SumithRamsookbhai/qa-shift-left-mcp
/plugin install sumo-qa@sumo-qa-dev
```

Then `uv tool install sumo-qa` (or `pip install sumo-qa`) so the MCP server binary is on PATH. The skills come from the plugin; the MCP tools come from the binary.

### Multi-host batch install (JetBrains + VS Code + everywhere)

```bash
python3 install.py
```

Configures every supported host detected on this machine. Per-host flags + troubleshooting in [docs/INSTALL.md](docs/INSTALL.md).

### From a git URL (latest main)

```bash
uv tool install --from git+https://github.com/SumithRamsookbhai/qa-shift-left-mcp.git sumo-qa
```

```

- [ ] **Step 5: Remove the "Status" line at the bottom**

Find the existing line that starts with `Branch \`feat/superpowers-restructure\`, validated end-to-end on...`. Delete that whole paragraph — it's release-notes content, not main-README content.

- [ ] **Step 6: Add License section near the bottom (just above Docs links if those exist, or as the last section)**

Insert this section:

```markdown
## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attribution requirements that apply to forks and redistributors.

```

- [ ] **Step 7: Verify the README renders without broken links**

```bash
grep -oE "\[.+?\]\(.+?\)" README.md | sort -u | head -30
```
Spot-check: all relative paths should resolve to actual files; absolute URLs should be `github.com/SumithRamsookbhai/qa-shift-left-mcp` and `pypi.org/project/sumo-qa`.

- [ ] **Step 8: Verify no test or build regression**

```bash
uv run pytest -q
```
Expected: `169 passed, 1 xfailed`.

- [ ] **Step 9: Commit**

```bash
git add README.md
git commit -m "docs(readme): badges, Why-sumo-qa value statement, install reordering

- Adds 4 status badges (tests CI, PyPI version, Python versions,
  Apache 2.0 license).
- Adds 'Why sumo-qa?' section between H1 and Setup — explains the
  senior-QA value to a reader who doesn't already know what
  shift-left QA is.
- Reorders Install: pip first (shortest), then /plugin install,
  then install.py multi-host, then git-URL.
- Drops the 'Status: validated on host X with model Y' line — that
  belongs in release notes, not main README.
- Adds License section pointing at LICENSE + NOTICE."
```

---

## Task 5: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm git history is clean**

```bash
git log --oneline main..HEAD
```
Expected: 4 new commits ahead of main (license, untracked-files, ci, readme).

- [ ] **Step 2: Confirm working tree is clean**

```bash
git status --short
```
Expected: only `knowledge/test_data/fulfilment/` and `knowledge/test_data/stock/` showing as untracked (those stay gitignored — they're JL-local fixtures).

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest -q
```
Expected: `169 passed, 1 xfailed`.

- [ ] **Step 4: Run ruff one more time**

```bash
uv run ruff check .
uv run ruff format --check .
```
Expected: both clean.

- [ ] **Step 5: Validate plugin manifests still parse**

```bash
python3 -c "import json; [json.load(open(p)) for p in ['.claude-plugin/plugin.json','.claude-plugin/marketplace.json','.cursor-plugin/plugin.json','.codex-plugin/plugin.json']]; print('all 4 manifests valid')"
```
Expected: `all 4 manifests valid`.

- [ ] **Step 6: Verify the wheel builds clean**

```bash
rm -rf dist/
uv build 2>&1 | tail -10
ls dist/
```
Expected: `sumo_qa-0.1.0-py3-none-any.whl` + `sumo_qa-0.1.0.tar.gz`, no warnings about license metadata.

- [ ] **Step 7: Inspect the wheel — does it include LICENSE + NOTICE?**

```bash
unzip -l dist/sumo_qa-0.1.0-py3-none-any.whl | grep -E "LICENSE|NOTICE"
```
Expected: both `LICENSE` and `NOTICE` listed inside the wheel's `*.dist-info/` directory.

- [ ] **Step 8: Print a summary for the user**

Surface to the user:
- Number of new commits on `feat/oss-prep` vs main
- Files added (counts by category)
- Test result counts
- Outstanding follow-ups: user creates GitHub remote → push → configure PyPI trusted publisher → tag v0.1.0 → verify

---

## Out of scope (deliberate YAGNI — reference only)

- CONTRIBUTING.md / CODE_OF_CONDUCT.md / issue+PR templates — add when real PRs arrive
- CHANGELOG.md — add after the second release
- release-please / semantic-release — add when manual tagging becomes painful
- Per-file copyright headers — repo-root LICENSE+NOTICE sufficient
- Documentation site (mkdocs / Sphinx) — `docs/` is already GitHub-browseable

---

## Open assumptions (flag during execution if any break)

- PyPI project name `sumo-qa` is available (fallback: `sumo-qa-mcp` — matches binary name).
- Repo URL `github.com/SumithRamsookbhai/qa-shift-left-mcp` matches what the user will create (refresh if not).
- `standards/packs/*.yml` confirmed free of internal references (already verified during planning).
