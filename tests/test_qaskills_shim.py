# Copyright 2026 Sumith Ramsookbhai. Licensed under Apache-2.0 (see LICENSE).
from __future__ import annotations

from unittest.mock import patch

from sumo_qa import qaskills


def test_is_available_returns_true_when_npx_present() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value="/usr/local/bin/npx") as mock_which:
        assert qaskills.is_available() is True
    mock_which.assert_called_once_with("npx")


def test_is_available_returns_false_when_npx_missing() -> None:
    with patch("sumo_qa.qaskills.shutil.which", return_value=None):
        assert qaskills.is_available() is False
