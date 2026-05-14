# Coverage floor + pragma policy

## Floor

sumo-qa enforces 100% statement coverage via `pytest --cov=src/sumo_qa --cov-fail-under=100` in CI. This is a deliberate quality bar — sumo-qa's purpose is delivering ISTQB-grade testing discipline to other repos, so it sets the bar for itself.

Note: 100% statement coverage ≠ 100% behaviour coverage. Statement coverage is a necessary floor; mutation testing (planned for Phase 3 of the QA strategy) is what validates behaviour confidence. See [docs/qa-strategy.md](qa-strategy.md) for the broader testing roadmap.

## Allowed pragmas

The following three cases justify a `# pragma: no cover` annotation:

### 1. Defensive sys.exit(1) after guards that can't be reached under test

When a code path is protected by a version check, environment check, or platform guard that cannot be satisfied in the test environment, you may pragma the defensive exit. Example:

```python
if sys.version_info < (3, 10):
    print("Python 3.10+ required")
    sys.exit(1)  # pragma: no cover -- defensive exit for unsupported Python version
```

This is acceptable because the test suite runs on Python 3.10+, so this path cannot execute. The pragma documents the guard condition clearly.

### 2. Platform-conditional branches unreachable on the test OS

Code that branches on platform-specific conditions (Windows, macOS, Linux) can be pragmaed when the current OS cannot reach that branch. One targeted pragma per branch — never wholesale. Example:

```python
if sys.platform == "win32":
    subprocess.run(["cmd.exe", "/c", "echo"], shell=True)  # pragma: no cover -- Windows-specific path
else:
    subprocess.run(["echo"], shell=False)
```

This is acceptable if tests run on macOS or Linux. The pragma identifies the unreachable platform explicitly.

### 3. `if __name__ == "__main__":` guards

Module-level entry points can be pragmaed:

```python
if __name__ == "__main__":  # pragma: no cover
    main()
```

This is acceptable because test suite entry is not via `python module.py` — it's via pytest or similar, so this guard is never reached.

## Disallowed pragmas

The following uses of `# pragma: no cover` are forbidden:

1. **Covering up untested logic.** If a code path is logically testable, it must have a test. Do not pragma around missing test cases.

2. **Suppressing flaky tests.** If a test is flaky, fix the flake. Do not pragma the test or the code it covers to silence it.

3. **"I'll come back to this later" pragmas.** Do not use pragmas as placeholders for future work. File an issue instead and leave the code unpragmaed until you're ready to defend the pragma against the allowed cases.

4. **Pragmas without an inline comment.** Every pragma must include a brief inline comment naming which allowed case (defensive exit, platform-conditional, or `__name__` guard) it falls under. A comment like `# pragma: no cover -- platform-conditional Windows path` is the minimum.

## How to add a pragma

When you discover a pragma is needed, follow this process:

1. **Justify it in the PR description** against the three allowed cases. State which case applies and why the path is unreachable under test.

2. **Include an inline comment** on the pragma line itself naming the allowed case. Example:
   ```python
   if sys.platform == "win32":  # pragma: no cover -- platform-conditional Windows path
       do_windows_thing()
   ```

3. **Get reviewer sign-off.** The reviewer must explicitly agree it falls under one of the three allowed cases before merge.

Without this process, the pragma will be rejected on review.

## Running coverage locally

To see what statements are uncovered:

```bash
uv run pytest --cov=src/sumo_qa --cov-report=term-missing
```

This shows a line-by-line coverage report with missing lines flagged.

To run the exact gate CI enforces:

```bash
uv run pytest --cov=src/sumo_qa --cov-fail-under=100
```

This will exit with a non-zero code if coverage falls below 100%.

## Lowering the floor

The floor stays at 100% as a deliberate quality bar. Lowering the floor is rare and requires:

1. **An amendment to [docs/qa-strategy.md](qa-strategy.md)** justifying the new floor with measurable reasoning (e.g., "platform-specific code is now 15% of the module and justified by XYZ").

2. **Maintainer sign-off** on the PR lowering the floor.

3. **A rationale in the PR description** explaining why the new floor is appropriate for sumo-qa's mission.

Routine drift (one new module under 100% that hasn't been tested yet) does NOT justify lowering the floor — it justifies adding tests for that module. The floor is a quality commitment, not a convenience.
