# Contributing to sumo-qa

Thanks for your interest in improving sumo-qa. This guide covers how to get set up, the checks your change needs to pass, and the conventions we follow.

By participating, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug** or **request a feature** through the [issue templates](https://github.com/sumithr/sumo-qa/issues/new/choose).
- **Improve the docs** under [`docs/`](../docs) or the skill catalogues under [`skills/`](../skills) and [`knowledge/`](../knowledge).
- **Fix a bug or add a capability** via a pull request (see below).

For anything security-related, do **not** open a public issue — follow the [Security Policy](SECURITY.md) instead.

## Development setup

The full local-dev guide lives in [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md). In short:

```bash
git clone https://github.com/sumithr/sumo-qa
cd sumo-qa
python -m venv .venv && source .venv/bin/activate   # or: uv sync --all-extras
python -m pip install -e ".[dev]"
pre-commit install --install-hooks                  # lint + hygiene on every commit
pre-commit install --hook-type pre-push             # full pytest suite on every push
```

## Before you push

The pre-commit hooks mirror CI, so passing them locally clears the lint and test gates. You can also run the checks on demand:

```bash
pre-commit run --all-files                          # ruff lint + format + hygiene
pytest                                              # full test suite
python -m mypy                                      # static type check (CI gate, not a hook)
```

A change is ready when ruff, pytest, and mypy are all green.

## Pull requests

- Branch off `main`; keep each PR focused on one logical change.
- **PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/)** (e.g. `fix:`, `feat:`, `docs:`, `ci:`, `chore:`). Releases are automated from PR titles via release-please, so a non-conforming title is silently dropped from the changelog — use a single valid type, not combined prefixes like `docs+test:`.
- Update the relevant docs in the same PR as the code change.
- Fill in the pull request template and link the issue your change addresses.
- New skills must use the `sumo-qa-` prefix and pass the conformance tests; see [`docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md#adding-a-new-skill).

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](../LICENSE), the same license that covers this project.
