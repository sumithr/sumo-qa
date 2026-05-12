# OSS-readiness — Design

> **Status:** Design approved 2026-05-12; remote GitHub repo URL pending (user creating). All work below is local-only until the URL lands, at which point a final patch pass sets the live URLs.

**Goal:** Make sumo-qa public-ready. Anyone can install with one line; CI proves green on every push; attribution preservation enforced via Apache 2.0's NOTICE-file mechanic. No active community-growth scaffolding (no CONTRIBUTING, no issue templates, no CHANGELOG) — those land later only if real PRs start coming in.

**Audience:** Public install for anyone; the user (Sumith Ramsookbhai) wants attribution preserved when colleagues fork/redistribute.

**Approach chosen:** "Lean OSS-prep + full CI" (Approach A from brainstorming).

---

## Section 1 — License + attribution mechanics

The user's stated concern is *"I don't want the colleagues I share it with to use it without giving me credit."* Apache 2.0 covers this via the NOTICE file: any redistribution MUST preserve the NOTICE file content. MIT only covers source-distribution preservation; Apache adds NOTICE-in-derivatives.

**Files to add at repo root:**

- `LICENSE` — full Apache 2.0 text (verbatim from apache.org/licenses/LICENSE-2.0.txt).
- `NOTICE` — 3 lines:
  ```
  sumo-qa
  Copyright 2026 Sumith Ramsookbhai
  Licensed under the Apache License, Version 2.0.
  ```

**Files to update:**

- `pyproject.toml`:
  - `license = "Apache-2.0"` (PEP 639 SPDX identifier — supported in hatchling)
  - Add `authors = [{name = "Sumith Ramsookbhai"}]`
  - Add `urls = { Homepage = "https://github.com/SumithRamsookbhai/qa-shift-left-mcp", Repository = "..." }` (URLs assumed; refresh if user picks different repo name when creating remote)
- `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `.cursor-plugin/plugin.json`, `.codex-plugin/plugin.json`:
  - `"license": "MIT"` → `"license": "Apache-2.0"`

**Source-file copyright headers:** NOT added. Repo-root LICENSE + NOTICE is sufficient per Apache 2.0; per-file headers add ~13 lines of overhead to every `.py` and `.md` for minimal additional protection.

**Docs touch:** README "License" section + docs/ARCHITECTURE.md note Apache 2.0.

---

## Section 2 — Commit pre-existing untracked files

These are load-bearing for public install and have been sitting untracked. Commit:

| File | Why it ships |
|---|---|
| `install.sh` | The "one-line install" front door. README will reference it. |
| `Dockerfile` | Containerised install path (already references Python 3.12 + project layout). |
| `.dockerignore` | Pairs with Dockerfile; excludes build artefacts. |
| `uv.lock` | Pinned dependency lockfile. Required for reproducible CI builds + faster cold installs. |
| `standards/packs/` | Sample standards packs (already wheel-bundled via `[tool.hatch.build.targets.wheel.force-include]`); commit the source dir so repo browsers can see examples. |

**Stays gitignored** (already in `.gitignore`):

- `knowledge/test_data/fulfilment/`, `knowledge/test_data/stock/` — local JL fixtures from the domain-neutrality pass.

---

## Section 3 — CI workflows under `.github/workflows/`

Three workflows + Dependabot config (Dependabot's `schedule:` block IS the "scheduled deps" coverage — no separate cron workflow needed).

### 3a. `test.yml`

- **Trigger:** `push` to any branch + `pull_request` to `main`.
- **Matrix:** Python `3.10` / `3.11` / `3.12` / `3.13` × OS `ubuntu-latest` / `macos-latest`. 8 combinations.
- **Steps:** checkout → install `uv` → `uv sync --all-extras` → `uv run pytest -q`.
- **Caches:** `~/.cache/uv` keyed by `pyproject.toml` + `uv.lock` hashes.

### 3b. `lint.yml`

- **Trigger:** same as test.
- **Steps:** checkout → install `uv` → `uv run ruff check .` → `uv run ruff format --check .`.
- **Dependency:** add `ruff` to `[project.optional-dependencies].dev` in pyproject. Ship a minimal `ruff.toml` (default rules + `line-length = 100`).

### 3c. `release.yml`

- **Trigger:** `push` of tag matching `v*` (e.g. `v0.1.0`).
- **Steps:** checkout → install `uv` → `uv build` → publish to PyPI via **trusted publishing (OIDC)** — no API tokens stored as secrets.
- **One-time setup** (documented in `docs/INSTALL.md` under "Maintainer notes"): create PyPI project `sumo-qa`, link to GH repo via Trusted Publisher (see [PyPI docs](https://docs.pypi.org/trusted-publishers/)). Documented but not automated.

### 3d. `.github/dependabot.yml` (covers "scheduled deps")

Dependabot's own weekly schedule is the cron — no separate workflow.

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
```

---

## Section 4 — Distribution paths

Three install paths, all documented:

1. **PyPI** (stable):
   ```bash
   pip install sumo-qa
   # or: uv tool install sumo-qa
   ```
   Released by `release.yml` on tag.

2. **Git URL** (current main / unreleased fixes):
   ```bash
   uv tool install --from git+https://github.com/SumithRamsookbhai/qa-shift-left-mcp.git sumo-qa
   ```

3. **Claude Code plugin** (existing, unchanged):
   ```text
   /plugin marketplace add SumithRamsookbhai/qa-shift-left-mcp
   /plugin install sumo-qa@sumo-qa-dev
   ```

`install.sh` continues to wrap path 2 for the bash-curl convenience case.

---

## Section 5 — README polish

Concrete changes:

- **Top of README** (above the heading): 4 status badges via shields.io
  - CI test workflow status
  - PyPI latest version
  - Python versions supported (`python-3.10|3.11|3.12|3.13`)
  - License (Apache 2.0)
- **Insert "Why sumo-qa?" section** (≤3 short paragraphs) directly after the H1 and before "Setup". Aimed at a reader who doesn't know what shift-left QA is or why senior-QA-shaped agents matter. Lead with the value, not the architecture.
- **"Setup" section reordered:**
  1. PyPI (`pip install sumo-qa`) — shortest, most familiar
  2. Claude Code plugin (`/plugin install`) — for native plugin users
  3. `install.py` (multi-host batch) — for JetBrains/VS Code users
- **"Status" line at the bottom** (the "validated on X with Y" line) — removed. That belongs in release notes, not the main README.
- **DEMO.md** stays linked in the existing "See it in action" section near the top.
- **License section** added at the bottom: *"Licensed under the Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE)."*

---

## Section 6 — First release flow

**Documented, not automated** for v0.1.0. After all the above lands and CI is green on a PR:

1. PR `feat/oss-prep` → `main`, review, merge.
2. (User step) Create GitHub repo at the user-provided URL.
3. (User step) `git remote add origin <url>` + `git push -u origin main`.
4. (User step) Configure PyPI Trusted Publisher (one-time, web UI).
5. `git tag v0.1.0 && git push origin v0.1.0` → `release.yml` builds + publishes the wheel.
6. Verify `pip install sumo-qa` from a fresh venv.

Step 3 needs the remote URL from the user. Steps 4–6 happen post-merge.

---

## Out of scope (deliberate YAGNI)

- CONTRIBUTING.md / CODE_OF_CONDUCT.md — re-evaluate if real PRs start arriving.
- CHANGELOG.md — re-evaluate after the second release.
- Issue / PR templates — add when there's actual signal of confused contributors.
- release-please / semantic-release — add when manual tagging becomes painful (probably 3+ releases in).
- Per-file copyright headers — repo-root LICENSE+NOTICE is sufficient.
- Documentation site (mkdocs / Sphinx) — `docs/` is already structured and browseable on GitHub.

---

## Open assumptions (flag and proceed)

- **PyPI project name `sumo-qa`** — assumed available. If squatted, fallback name `sumo-qa-mcp` (matches the binary name).
- **Repo URL `github.com/SumithRamsookbhai/qa-shift-left-mcp`** — matches what's already in plugin manifests; will be confirmed when user provides the actual remote URL.
- **`standards/packs/` committable** — assumed sample-only / no internal content. Will be inspected during commit prep; if anything internal-looking surfaces, kept gitignored instead.

---

## Success criteria

- [ ] `pip install sumo-qa` works from a fresh venv (post-publish).
- [ ] `uv tool install --from git+...` works from the GitHub URL (post-push).
- [ ] CI green on the merge PR (test + lint workflows both pass on the matrix).
- [ ] `LICENSE` + `NOTICE` present at repo root; Apache 2.0 reflected in all manifests.
- [ ] README opens with badges, value statement, then quick-install — no architecture-first wall of text.
- [ ] Existing 169 tests still pass.

---

## Branch + commit strategy

Working branch: `feat/oss-prep` (already created from `main`).

Commits aimed to be logical, reviewable chunks:

1. `docs(license): adopt Apache 2.0 + add LICENSE + NOTICE`
2. `chore: commit install.sh + Dockerfile + .dockerignore + uv.lock + standards/packs`
3. `ci: test + lint + release workflows + dependabot config`
4. `chore: add ruff to dev extras + ruff.toml`
5. `docs(readme): badges, value statement, install reordering, license section`

PR title: `OSS-readiness: license, CI, docs polish for public release`.
