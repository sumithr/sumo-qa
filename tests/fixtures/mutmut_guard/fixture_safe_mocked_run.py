# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
"""SAFE fixture: ``subprocess.run`` is monkeypatched, and the command list
``["-m", "sumo_qa"]`` is only *asserted on*, never actually spawned.

Shape from ``tests/test_installer_idempotency.py`` / ``test_external_skills.py``.
No fresh interpreter is launched, so there is no trampoline hazard and the guard
must NOT flag it, even though the source mentions ``sumo_qa`` and ``-m``. Fixture,
not a test (named ``fixture_*.py``).
"""

from __future__ import annotations


def assert_module_fallback_args(monkeypatch, ext) -> None:
    monkeypatch.setattr(ext.subprocess, "run", lambda *a, **k: None)
    # The contract is "the installer passes -m sumo_qa", checked by inspecting
    # the recorded args — no real spawn, so no mutated-module import occurs.
    expected = ["-m", "sumo_qa"]
    assert expected == ["-m", "sumo_qa"]
