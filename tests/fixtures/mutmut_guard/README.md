# mutmut subprocess-guard fixtures

Real, runnable subprocess-spawn shapes used by
`tests/test_mutmut_subprocess_exclusions.py` to prove the static guard
(`_spawns_subprocess_importing_mutated_code`) classifies each shape correctly.

These are **fixtures, not tests** — they are named `fixture_*.py` (not `test_*.py`)
so pytest does not collect them and the production guard's `tests/test_*.py`
glob does not treat them as real suite files. Each file is a faithful copy of a
shape that occurs (or could plausibly be added) in the real suite:

| File | Shape | Expected verdict |
| --- | --- | --- |
| `fixture_hazard_dash_c_dedent_var.py` | `code = textwrap.dedent("...import sumo_qa.knowledge_loaders...")`; `subprocess.run([sys.executable, "-c", code])` | HAZARD (FN #1) |
| `fixture_hazard_dash_m_server.py` | `subprocess.run([sys.executable, "-m", "sumo_qa.server"])` | HAZARD (FN #2) |
| `fixture_safe_dash_m_installer.py` | `subprocess.run([sys.executable, "-m", "sumo_qa.installer", "--help"])` | safe (non-mutating entry point) |
| `fixture_safe_mocked_run.py` | monkeypatched `subprocess.run`, asserts on `["-m", "sumo_qa"]` without spawning | safe (mock) |
| `fixture_safe_git_spawn.py` | `subprocess.run(["git", "init", "-q"], ...)` | safe (not a Python spawn) |
| `fixture_safe_script_path.py` | `subprocess.run([sys.executable, str(SCRIPT)])` (a hook script, not `-m sumo_qa`) | safe (non-package entry) |
| `fixture_safe_bare_string_mention.py` | a docstring/string that *names* `sumo_qa.knowledge_loaders` but spawns nothing | safe (no spawn) |

The two HAZARD fixtures are the exact false-negatives issue #195's review found:
both passed the *pre-fix* guard silently, which would have let a new
subprocess-spawning test disarm the mutmut gate.
