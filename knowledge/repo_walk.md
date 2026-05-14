# Repo Walk Recipe

Fixed inventory recipe for `sumo-qa-strategising`. Run these commands in order to collect consistent
inventory data across strategy sessions on the same repo state.

---

## Inventory commands

**Top-level structure** — map directories to depth 2, excluding hidden dirs and common build artifacts:

```bash
find . -maxdepth 2 -type d \
  -not -path '*/\.*' \
  -not -path './node_modules*' \
  -not -path './.venv*' \
  | sort
```

**Source LOC** — lines of code per source file, ascending (substitute `<package>` with the actual package name):

```bash
ls src/<package>/*.py | xargs wc -l | sort -n
```

**Test LOC** — lines of code per test file, ascending:

```bash
ls tests/*.py | xargs wc -l | sort -n
```

**Test count** — total collected test items:

```bash
pytest --co -q | tail -1
```

**Coverage per module** — coverage with missing-line detail (substitute `<package>`):

```bash
pytest --cov=src/<package> --cov-report=term-missing -q | tail -25
```

**CI matrix axes** — Python versions, OSes, and step commands declared in workflows:

```bash
cat .github/workflows/*.yml | grep -E "^name:|run:|matrix:|os:|python-version:"
```

**Pre-commit hooks** — static-layer tools wired into the repo:

```bash
cat .pre-commit-config.yaml | grep -E "id:|hooks:"
```

---

## Data shape captured

| Datum | Where it comes from | Use in strategy |
|---|---|---|
| Top-level dirs | `find . -maxdepth 2 ...` | Inventory section |
| Source modules + LOC | `ls src/.../*.py + wc -l` | Per-module risk anchoring |
| Test files + LOC | `ls tests/*.py + wc -l` | Coverage gap analysis |
| Test count | `pytest --co -q` | Suite size baseline |
| Coverage % per module | `pytest --cov ...` | Identifying highest-gap modules |
| CI matrix axes | `.github/workflows/*.yml` | Cross-platform / Python-version coverage gaps |
| Pre-commit hooks | `.pre-commit-config.yaml` | Static-layer baseline |
| Languages / frameworks | inferred from file inventory | Shape of test pyramid |

Each datum maps to a named row in the `## Inventory` section of the strategy document (see Output template below).

Example of how to cross-reference:

```
coverage % per module → rank by gap → highest-gap modules become Phase 1 targets
CI matrix axes        → missing OS or Python version → explicit risk if production differs
Pre-commit hooks      → none detected → static layer is absent → recommend linting gate
```

---

## Output template

Paste this template into the strategy document's `## Inventory` section and fill in the values gathered
from the commands above.

```markdown
## Inventory

| Area | Files | LOC (src) | LOC (tests) | Test count | Coverage | Notes |
|---|---|---|---|---|---|---|
| `<module-or-service>` | `<src/pkg/module.py>` | NNN | NNN | NN | NN% | e.g. no integration tests |
| `<module-or-service>` | `<src/pkg/module.py>` | NNN | NNN | NN | NN% | e.g. no tests at all |

**CI matrix:** Python `<versions>`, OS `<platforms>` — `<gaps noted or "no gaps">`

**Static layer:** `<hooks listed or "no pre-commit config detected">`

**Frameworks detected:** `<e.g. FastAPI + pytest + ruff>`

**Total test count:** NN tests collected

**Overall coverage:** NN%
```
