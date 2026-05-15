#!/usr/bin/env python3
"""Walk knowledge/test_data/**/*.yaml and HEAD every URL value found.

Used by .github/workflows/tdm-freshness.yml on a weekly cron to detect
known-good test-data entries that point at URLs which have rotted
(non-2xx response).

The script walks ALL *.yaml files under knowledge/test_data/ (not only
files named known_good.yaml) so it stays useful as the naming convention
for test-data files evolves.  URL detection uses a full recursive walk of
every parsed value — any string starting with "http://" or "https://" is
treated as a URL to check.  Over-checking is intentional: it is always
safer to flag a URL that turned out to be fine than to silently miss one.

Exit code:
  0 — all URLs reachable (2xx), OR no URLs found at all
  1 — at least one URL returned non-2xx or a network error;
      details are printed to stdout
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TDM_ROOT = REPO_ROOT / "knowledge" / "test_data"

TIMEOUT_SECONDS = 10


def _walk_for_urls(node: object) -> list[str]:
    """Recursively collect string values that look like HTTP(S) URLs."""
    urls: list[str] = []
    if isinstance(node, dict):
        for v in node.values():
            urls.extend(_walk_for_urls(v))
    elif isinstance(node, list):
        for item in node:
            urls.extend(_walk_for_urls(item))
    elif isinstance(node, str) and (node.startswith("http://") or node.startswith("https://")):
        urls.append(node)
    return urls


def _check(url: str) -> tuple[str, int | str]:
    """HEAD *url*.  Return (url, status_code) or (url, error_string)."""
    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            return (url, resp.status)
    except urllib.error.HTTPError as exc:
        return (url, exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return (url, f"ERROR: {exc}")


def main() -> int:
    if not TDM_ROOT.is_dir():
        print(f"No TDM root at {TDM_ROOT}; nothing to check.")
        return 0

    urls: set[str] = set()
    yaml_files = sorted(TDM_ROOT.rglob("*.yaml"))

    if not yaml_files:
        print("No *.yaml files found under knowledge/test_data/; nothing to check.")
        return 0

    for yaml_path in yaml_files:
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(f"YAML parse error in {yaml_path}: {exc}", file=sys.stderr)
            continue
        if data is not None:
            urls.update(_walk_for_urls(data))

    if not urls:
        print(
            f"Checked {len(yaml_files)} YAML file(s) under {TDM_ROOT}; "
            "no HTTP(S) URLs found — nothing to probe."
        )
        return 0

    print(f"Checking {len(urls)} unique URL(s) across {len(yaml_files)} file(s)...")
    failures: list[tuple[str, int | str]] = []

    for url in sorted(urls):
        result_url, status = _check(url)
        if isinstance(status, int) and 200 <= status < 300:
            print(f"  [OK]   {status}  {result_url}")
        else:
            print(f"  [FAIL] {status}  {result_url}")
            failures.append((result_url, status))

    if failures:
        print(f"\n{len(failures)} URL(s) failed freshness check:")
        for url, status in failures:
            print(f"  {status}\t{url}")
        return 1

    print(f"\nAll {len(urls)} URL(s) OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
