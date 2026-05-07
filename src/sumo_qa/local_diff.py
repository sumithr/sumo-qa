from __future__ import annotations

import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


_DIFF_GIT_HEADER = re.compile(r"^diff --git a/(.+) b/(.+)$")
_MIN_NEARBY_TEST_SCORE = 50


@dataclass(frozen=True)
class LocalDiffReport:
    diff_source: str
    diff_available: bool
    touched_files: list[str] = field(default_factory=list)
    nearby_tests: list[str] = field(default_factory=list)
    risky_untested_changes: list[str] = field(default_factory=list)
    missing_test_levels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class LocalDiffInspector:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)
        self._test_candidates: list[Path] | None = None

    def _invalidate_cache(self) -> None:
        self._test_candidates = None

    def inspect(
        self,
        diff: str | None,
        touched_files: list[str] | None,
        expected_test_types: list[str],
        test_evidence: list[str],
    ) -> tuple[str, LocalDiffReport]:
        effective_diff = diff or self._git_diff()
        source = "provided" if diff else "git diff"
        files = sorted(set(touched_files or _files_from_diff(effective_diff)))
        nearby_tests = self._nearby_tests(files)
        observed_levels = _observed_test_levels(nearby_tests, test_evidence)
        missing_levels = [
            level
            for level in expected_test_types
            if level in {"unit", "integration", "contract", "functional", "nonfunctional"} and level not in observed_levels
        ]
        risky_untested = []
        if files and missing_levels:
            risky_untested.append(
                f"Changed files have no clear evidence for expected levels: {', '.join(missing_levels)}."
            )
        if files and not nearby_tests and not test_evidence:
            risky_untested.append("No nearby tests or supplied evidence were found for the touched files.")

        return effective_diff, LocalDiffReport(
            diff_source=source,
            diff_available=bool(effective_diff.strip()),
            touched_files=files,
            nearby_tests=nearby_tests,
            risky_untested_changes=risky_untested,
            missing_test_levels=missing_levels,
        )

    def _git_diff(self) -> str:
        try:
            completed = subprocess.run(
                ["git", "diff", "--no-ext-diff"],
                cwd=self.root,
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if completed.returncode != 0:
            return ""
        return completed.stdout

    def _nearby_tests(self, files: list[str], limit: int = 10) -> list[str]:
        if not files:
            return []
        candidates = self._load_test_candidates()
        scored: dict[str, int] = {}
        for changed in files:
            changed_path = Path(changed)
            changed_stem = changed_path.stem.lower()
            changed_tokens = {
                token
                for token in changed_stem.replace("-", "_").split("_")
                if len(token) > 2
            }
            changed_parent = changed_path.parent.as_posix().lower()
            for candidate in candidates:
                relative = candidate.relative_to(self.root).as_posix()
                candidate_path = Path(relative)
                candidate_stem = candidate_path.stem.lower()
                candidate_tokens = set(candidate_stem.replace("-", "_").split("_"))
                score = _match_score(
                    changed_stem=changed_stem,
                    changed_tokens=changed_tokens,
                    changed_parent=changed_parent,
                    candidate_stem=candidate_stem,
                    candidate_tokens=candidate_tokens,
                    candidate_parent=candidate_path.parent.as_posix().lower(),
                )
                if score < _MIN_NEARBY_TEST_SCORE:
                    continue
                scored[relative] = max(score, scored.get(relative, 0))
        ranked = sorted(scored.items(), key=lambda item: (-item[1], item[0]))
        return [relative for relative, _ in ranked[:limit]]

    def _load_test_candidates(self) -> list[Path]:
        if self._test_candidates is None:
            self._test_candidates = [
                path
                for path in self.root.rglob("*")
                if path.is_file()
                and ".venv" not in path.parts
                and "__pycache__" not in path.parts
                and ("test" in path.name.lower() or "tests" in path.parts)
            ]
        return self._test_candidates


def _match_score(
    *,
    changed_stem: str,
    changed_tokens: set[str],
    changed_parent: str,
    candidate_stem: str,
    candidate_tokens: set[str],
    candidate_parent: str,
) -> int:
    if not changed_stem:
        return 0
    score = 0
    if candidate_stem == changed_stem:
        score += 100
    elif candidate_stem in {f"test_{changed_stem}", f"{changed_stem}_test"}:
        score += 90
    elif changed_stem in candidate_tokens:
        score += 50
    overlap = changed_tokens.intersection(candidate_tokens)
    if overlap:
        score += 10 * len(overlap)
    if score > 0 and changed_parent and candidate_parent.startswith(changed_parent):
        score += 5
    return score


def _files_from_diff(diff: str) -> list[str]:
    files: set[str] = set()
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.add(line.removeprefix("+++ b/"))
        elif line.startswith("--- a/"):
            files.add(line.removeprefix("--- a/"))
        elif line.startswith("rename from "):
            files.add(line.removeprefix("rename from "))
        elif line.startswith("rename to "):
            files.add(line.removeprefix("rename to "))
        elif line.startswith("diff --git "):
            match = _DIFF_GIT_HEADER.match(line)
            if match:
                files.add(match.group(1))
                files.add(match.group(2))
    return sorted(file for file in files if file and file != "/dev/null")


def _observed_test_levels(nearby_tests: list[str], test_evidence: list[str]) -> set[str]:
    text = " ".join([*nearby_tests, *test_evidence]).lower()
    observed: set[str] = set()
    for level in ["unit", "integration", "contract", "functional", "nonfunctional"]:
        if level in text:
            observed.add(level)
    if any("test" in item.lower() for item in nearby_tests):
        observed.add("unit")
    return observed
