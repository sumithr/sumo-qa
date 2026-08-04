# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""Tests for the shared mutation-gate verdict script.

The gate script exists because `mutmut run` exits 0 even when mutants
survive (root-caused 2026-07-13; PR #302's 47 survivors reached main through
a pre-push hook that trusted mutmut's exit code). These tests pin the verdict
semantics both the nightly workflow and the pre-push hook rely on: a wrong
verdict here silently greenlights weak tests.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    raise RuntimeError(f"no .git ancestor of {here!s}")


def _load_gate():
    path = _repo_root() / "scripts" / "check_mutation_gate.py"
    spec = importlib.util.spec_from_file_location("check_mutation_gate", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load_gate()


def _rewrite_meta(tmp_path, metas):
    """Overwrite the .meta files in place, used by the converge-loop stubs to
    simulate a later mutmut pass producing different results."""
    meta_root = tmp_path / "mutants" / "src" / "sumo_qa"
    for module, exit_codes in metas.items():
        (meta_root / f"{module}.py.meta").write_text(
            json.dumps({"exit_code_by_key": exit_codes}), encoding="utf-8"
        )


def _write_fixtures(tmp_path, baseline, metas):
    baseline_path = tmp_path / "mutmut-baseline.json"
    baseline_path.write_text(json.dumps({"per_module": baseline}), encoding="utf-8")
    meta_root = tmp_path / "mutants" / "src" / "sumo_qa"
    meta_root.mkdir(parents=True)
    for module, exit_codes in metas.items():
        (meta_root / f"{module}.py.meta").write_text(
            json.dumps({"exit_code_by_key": exit_codes}), encoding="utf-8"
        )
    return ["--baseline", str(baseline_path), "--meta-root", str(meta_root)]


def test_all_killed_at_baseline_passes(tmp_path, capsys):
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 2}},
        {"mod": {"m1": 1, "m2": 3}},
    )
    assert gate.main(argv) == 0
    out = capsys.readouterr().out
    assert "| mod | 2 | 2 | 0 | OK |" in out
    assert "Strict gate passed" in out


def test_survivor_fails_and_is_named(tmp_path, capsys):
    """The load-bearing case: mutmut itself exits 0 on survivors, so the gate
    MUST fail from the .meta contents alone."""
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 1}},
        {"mod": {"m_killed": 1, "m_survivor": 0}},
    )
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "| mod | 1 | 1 | 1 | SURVIVED |" in out
    assert "100% kill rate required" in out
    assert "m_survivor" in out  # triage can start without re-running mutmut


def test_killed_drop_below_baseline_fails(tmp_path, capsys):
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 3}},
        {"mod": {"m1": 1, "m2": 34}},  # 1 killed, 1 skipped
    )
    assert gate.main(argv) == 1
    assert "killed dropped from 3 -> 1" in capsys.readouterr().out


def test_missing_meta_file_fails(tmp_path, capsys):
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 1}}, {})
    assert gate.main(argv) == 1
    out = capsys.readouterr().out
    assert "| mod | 1 | 0 | 0 | MISSING |" in out
    assert "did mutmut run complete" in out


def test_skipped_and_timeout_codes_do_not_count_as_survivors(tmp_path, capsys):
    """Only exit code 0 is a survivor; 34 (skipped) and 36 (timeout) are not,
    and the full killed set is exactly {1, 3, -24}."""
    argv = _write_fixtures(
        tmp_path,
        {"mod": {"killed": 3}},
        {"mod": {"m1": 1, "m2": 3, "m3": -24, "m4": 34, "m5": 36}},
    )
    assert gate.main(argv) == 0
    assert "| mod | 3 | 3 | 0 | OK |" in capsys.readouterr().out


def test_github_step_summary_written_when_env_set(tmp_path, monkeypatch):
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 1}}, {"mod": {"m1": 1}})
    assert gate.main(argv) == 0
    assert "## Mutation gate" in summary_file.read_text(encoding="utf-8")


def test_crashed_mutmut_run_propagates_without_judging_stale_meta(tmp_path, monkeypatch, capsys):
    """--run-mutmut with a non-zero mutmut exit must NOT read the baseline or the
    .meta files: a crashed run leaves stale results, and judging them is a false
    verdict.

    Runs from an EMPTY cwd on purpose. Without the chdir this test passes even
    when main() reads the baseline eagerly, because pytest's cwd is the repo
    root where mutmut-baseline.json exists -- it would pass against a broken
    implementation, which is no test at all. The chdir is also what reproduces
    the real failure: the gate runs inside mutmut's own `mutants/` working copy
    during the clean-test phase, and the baseline is not copied there, so an
    eager read raises FileNotFoundError and aborts the whole mutation run.
    """
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd

        class R:
            returncode = 7

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    assert not (tmp_path / "mutmut-baseline.json").exists()
    assert gate.main(["--run-mutmut", "--max-children", "1"]) == 7
    assert calls["cmd"] == ["mutmut", "run", "--max-children", "1"]
    assert "not judging stale .meta files" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# macOS fork-noise converge loop (#523)
#
# On macOS the fork-based runner intermittently produces a run in which most
# mutants yield no usable verdict: either a segfault (-11/-9) or, when the run
# aborts before executing them, the `null` that mutmut pre-populates
# exit_code_by_key with at generation time. Neither is in KILLED_EXIT_CODES nor
# equals 0, so both collapse to killed=0/survived=0 and the gate reports every
# module DROPPED on a clean tree, blocking the push. An enforced-but-flaky gate
# trains people to bypass it, which defeats the enforcement it exists for.
# ---------------------------------------------------------------------------


def test_segfault_and_null_both_count_as_unjudged_not_killed_or_survived():
    """The two shapes of a wiped-out run. `null` matters as much as -11: mutmut
    pre-populates every key with null, so an abort-before-execute looks
    identical to a segfault in the verdict."""
    stats = gate.module_stats_from_exit_codes(
        {"seg": -11, "sigkill": -9, "never_ran": None, "killed": 1, "survivor": 0}
    )
    assert stats["killed"] == 1
    assert stats["survived"] == 1
    assert stats["unjudged"] == 3


def test_not_measured_detection_has_no_threshold():
    """No threshold is sound here: the baseline stores counts, not identities, so
    a shortfall can never be attributed to the mutants that went un-judged. A
    single un-judged mutant means the module was not fully measured."""
    assert gate.module_not_measured({"unjudged": 1, "total": 1000}) is True
    assert gate.module_not_measured({"unjudged": 0, "total": 1000}) is False
    assert gate.any_not_measured({"a": {"unjudged": 0}, "b": {"unjudged": 1}}) is True
    assert gate.any_not_measured({"a": {"unjudged": 0}, "b": {"unjudged": 0}}) is False


def test_merge_passes_never_erases_a_survivor_seen_in_an_earlier_pass():
    """P1: mutmut re-initialises verdicts on a later run, so a survivor observed
    in pass 1 can come back un-judged in pass 2. Judging only the final pass
    would let the retry launder a real survivor."""
    pass1 = {
        "mod": {"killed": 0, "survived": 1, "unjudged": 3, "total": 4, "survivor_names": ["s"]}
    }
    pass2 = {"mod": {"killed": 3, "survived": 0, "unjudged": 1, "total": 4, "survivor_names": []}}
    merged = gate.merge_passes(pass1, pass2)
    assert merged["mod"]["survivor_names"] == ["s"]
    assert merged["mod"]["survived"] == 1
    assert merged["mod"]["killed"] == 3, "best observed kill count is kept"
    assert merged["mod"]["unjudged"] == 1, "un-judged takes the converged value"


def test_converge_loop_reruns_keeping_cache_until_noise_clears(tmp_path, monkeypatch, capsys):
    """R2: the loop must re-run mutmut when the pass was noise-degraded, and it
    must NOT pass --clean/rm the cache; keeping the cache is what lets the
    surviving results accumulate across passes."""
    runs = []
    metas = [
        {"mod": {"m1": -11, "m2": -11, "m3": -11}},  # pass 1: wiped out
        {"mod": {"m1": 1, "m2": 1, "m3": 1}},  # pass 2: converged
    ]

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        _rewrite_meta(tmp_path, metas[len(runs) - 1])

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 3}}, metas[0])
    assert gate.main(["--run-mutmut", *argv]) == 0
    assert len(runs) == 2, "should re-run exactly once, then stop when clean"
    assert not any("--clean" in c for c in runs), "cache must be kept across passes"
    assert "converging (pass 2)" in capsys.readouterr().out


def test_converge_loop_is_bounded(tmp_path, monkeypatch, capsys):
    """R2: a permanently-noisy machine must not loop forever, since the push has to
    terminate one way or the other."""
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        _rewrite_meta(tmp_path, {"mod": {"m1": -11, "m2": -11, "m3": -11}})

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 3}}, {"mod": {"m1": -11}})
    rc = gate.main(["--run-mutmut", *argv])
    assert len(runs) == gate.MAX_CONVERGE_PASSES
    assert gate.MAX_CONVERGE_PASSES <= 2, (
        "a pass costs ~6 min in a synchronous pre-push hook; a blocked push must "
        "not become a 24-minute one"
    )
    assert rc == 0, "an un-measurable local run must not block the push"
    assert "un-measured" in capsys.readouterr().out


def test_linux_path_takes_no_extra_passes_and_sets_no_fork_env(tmp_path, monkeypatch):
    """R3 + AC3: a clean non-darwin run must call mutmut exactly once and must
    not inject the macOS-only fork-safety variable."""
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append((cmd, kwargs.get("env")))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    monkeypatch.setattr(gate.sys, "platform", "linux")
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 1}}, {"mod": {"m1": 1}})
    assert gate.main(["--run-mutmut", *argv]) == 0
    assert len(runs) == 1
    assert runs[0][1] is None, "no env override on Linux"


def test_darwin_sets_objc_fork_safety_in_child_env(tmp_path, monkeypatch):
    """The documented prerequisite for a usable local run; without it nearly
    every mutant segfaults."""
    runs = []

    def fake_run(cmd, **kwargs):
        runs.append(kwargs.get("env"))

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 1}}, {"mod": {"m1": 1}})
    assert gate.main(["--run-mutmut", *argv]) == 0
    assert runs[0]["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] == "YES"
    assert "PATH" in runs[0], "must extend os.environ, not replace it"


def _run_local_darwin(tmp_path, monkeypatch, baseline, metas):
    """Drive main() down the LOCAL macOS --run-mutmut path with mutmut stubbed to
    a no-op, so the noise tolerance is in force."""
    monkeypatch.setattr(gate.sys, "platform", "darwin")

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    argv = _write_fixtures(tmp_path, baseline, metas)
    return gate.main(["--run-mutmut", *argv])


def test_noise_degraded_does_not_block_the_local_push(tmp_path, monkeypatch, capsys):
    """The whole point of #523: a clean tree must push green locally when the
    module was not measured at all (2 of 3 mutants un-judged)."""
    rc = _run_local_darwin(
        tmp_path, monkeypatch, {"mod": {"killed": 3}}, {"mod": {"m1": 1, "m2": -11, "m3": -11}}
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOT-MEASURED" in out
    assert "Linux" in out, "must point at the authoritative gate"
    assert "Strict gate passed" not in out, "must not claim a gate it did not enforce"
    assert "makes no claim" in out, "exit 0 must mean 'not blocking', not 'clean'"


def test_linux_ci_path_keeps_strict_semantics_and_still_fails(tmp_path, capsys):
    """P1: the noise tolerance is a LOCAL affordance. The nightly workflow runs
    this script with no --run-mutmut, so the identical .meta that is tolerated
    locally must still be a hard DROPPED on the authoritative gate."""
    argv = _write_fixtures(
        tmp_path, {"mod": {"killed": 3}}, {"mod": {"m1": 1, "m2": -11, "m3": -11}}
    )
    assert gate.main(argv) == 1
    assert "killed dropped from 3 -> 1" in capsys.readouterr().out


def test_a_real_drop_hidden_by_noise_locally_is_still_caught_on_ci(tmp_path, monkeypatch, capsys):
    """The honest limit of the local gate, pinned on purpose.

    `c` genuinely regressed (34 = skipped, was a kill) and `d` is un-judged. The
    baseline holds counts, not mutant identities, so NOTHING can attribute the
    shortfall locally: the run simply did not measure this module. So the local
    path reports NOT-MEASURED and does not block, deliberately making no claim.

    What stops that regression reaching main is the CI path, which is strict:
    the SAME .meta must still be a hard DROPPED there. If this test ever starts
    passing on both paths, the safety net is gone.
    """
    metas = {"mod": {"a": 1, "b": 1, "c": 34, "d": -11}}
    baseline = {"mod": {"killed": 3}}

    rc_local = _run_local_darwin(tmp_path, monkeypatch, baseline, metas)
    local_out = capsys.readouterr().out
    assert rc_local == 0, "local is advisory: it must not block"
    assert "NOT-MEASURED" in local_out
    assert "Strict gate passed" not in local_out

    ci_dir = tmp_path / "ci"
    ci_dir.mkdir()
    argv = _write_fixtures(ci_dir, baseline, metas)
    assert gate.main(argv) == 1, "CI must still catch the drop the local run could not judge"
    assert "killed dropped from 3 -> 2" in capsys.readouterr().out


def test_survivor_still_fails_in_a_noise_degraded_run(tmp_path, monkeypatch, capsys):
    """The load-bearing one: a real survivor is a real failure no matter how
    noisy the rest of the run was. Noise must never launder a survivor."""
    rc = _run_local_darwin(
        tmp_path,
        monkeypatch,
        {"mod": {"killed": 1}},
        {"mod": {"m_survivor": 0, "m1": -11, "m2": -11, "m3": -11}},
    )
    assert rc == 1
    out = capsys.readouterr().out
    assert "100% kill rate required" in out
    assert "m_survivor" in out


def test_survivor_from_an_earlier_pass_survives_the_converge_loop(tmp_path, monkeypatch, capsys):
    """P1 end-to-end: pass 1 sees a survivor amid noise, pass 2 comes back clean
    with that mutant un-judged. Evaluating only the final pass would green it."""
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    runs = []
    metas = [
        {"mod": {"s": 0, "a": -11, "b": -11, "c": -11}},  # survivor + wipeout
        {"mod": {"s": None, "a": 1, "b": 1, "c": 1}},  # survivor now un-judged
    ]

    def fake_run(cmd, **kwargs):
        runs.append(cmd)
        _rewrite_meta(tmp_path, metas[min(len(runs) - 1, len(metas) - 1)])

        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 3}}, metas[0])
    assert gate.main(["--run-mutmut", *argv]) == 1, "the pass-1 survivor must still fail the gate"
    out = capsys.readouterr().out
    assert "100% kill rate required" in out
    assert "s" in out


def test_unjudged_mutant_is_not_measured_even_when_kill_floor_is_met(tmp_path, monkeypatch, capsys):
    """P1: the invariant is 'any un-judged mutant means this module was not
    measured', and that must hold regardless of the kill count. A module at or
    above baseline with an un-judged mutant previously fell through to OK and
    the run printed 'Strict gate passed', which is the unearned pass claim this
    design exists to prevent. Newly-generated mutants going un-judged is the
    realistic case."""
    rc = _run_local_darwin(
        tmp_path,
        monkeypatch,
        {"mod": {"killed": 1}},
        {"mod": {"a": 1, "b": -11}},  # kill floor met, one un-judged
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "NOT-MEASURED" in out
    assert "Strict gate passed" not in out, "must not claim a gate it did not enforce"


def test_merge_keeps_earlier_pass_when_a_later_meta_goes_missing():
    """P1: a pass whose .meta vanished carries no information. Folding its zeros
    in would wipe the earlier pass's un-judged count and make an un-measured
    module read as fully measured."""
    pass1 = {"mod": {"killed": 1, "survived": 0, "unjudged": 1, "total": 2, "missing": False}}
    pass2 = {"mod": {"killed": 0, "survived": 0, "unjudged": 0, "total": 0, "missing": True}}
    merged = gate.merge_passes(pass1, pass2)
    assert merged["mod"]["unjudged"] == 1, "un-measured state must survive a missing later pass"
    assert gate.any_not_measured(merged) is True


def test_tolerance_requires_darwin_not_just_run_mutmut(tmp_path, monkeypatch, capsys):
    """P3: pins the platform half of the guard. An implementation broken to
    `tolerate = bool(args.run_mutmut)` would let a NOISY non-darwin run reach
    NOT-MEASURED; with clean metadata only, that break is invisible."""
    monkeypatch.setattr(gate.sys, "platform", "linux")

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 0

        return R()

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    argv = _write_fixtures(tmp_path, {"mod": {"killed": 3}}, {"mod": {"a": 1, "b": -11, "c": -11}})
    assert gate.main(["--run-mutmut", *argv]) == 1, "non-darwin must stay strict even with noise"
    out = capsys.readouterr().out
    assert "NOT-MEASURED" not in out
    assert "killed dropped from 3 -> 1" in out


def test_merge_keeps_earlier_pass_when_a_later_meta_is_empty_or_truncated():
    """P1: guarding on `missing` alone was not enough. An EXISTING but empty
    .meta reports missing=False with zeroed counts, and a truncated one reports
    fewer mutants than the prior pass; folding either in wipes the earlier
    pass's un-judged count and an un-measured module reads as measured. The
    honest signal is population size, not file existence."""
    pass1 = {"mod": {"killed": 1, "survived": 0, "unjudged": 1, "total": 2, "missing": False}}

    empty = {"mod": {"killed": 0, "survived": 0, "unjudged": 0, "total": 0, "missing": False}}
    merged_empty = gate.merge_passes(pass1, empty)
    assert merged_empty["mod"]["unjudged"] == 1
    assert gate.any_not_measured(merged_empty) is True

    truncated = {"mod": {"killed": 1, "survived": 0, "unjudged": 0, "total": 1, "missing": False}}
    merged_trunc = gate.merge_passes(pass1, truncated)
    assert merged_trunc["mod"]["unjudged"] == 1, "a shrunken population is not a measurement"
    assert gate.any_not_measured(merged_trunc) is True


def test_merge_still_accepts_a_pass_that_measured_at_least_as_much():
    """The complement: a fresh pass covering the same or a larger population IS
    informative and must be folded in, or the converge loop could never
    converge."""
    pass1 = {"mod": {"killed": 0, "survived": 0, "unjudged": 2, "total": 2, "missing": False}}
    pass2 = {"mod": {"killed": 2, "survived": 0, "unjudged": 0, "total": 2, "missing": False}}
    merged = gate.merge_passes(pass1, pass2)
    assert merged["mod"]["unjudged"] == 0
    assert merged["mod"]["killed"] == 2
    assert gate.any_not_measured(merged) is False
