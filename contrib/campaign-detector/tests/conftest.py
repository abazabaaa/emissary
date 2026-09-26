"""Shared fixtures.

Two parametrized fixtures cover every registered scenario:

* ``scenario`` carries ``xfail(strict=True)`` when the scenario declares a
  ``known_gap`` -- use it for tests that run the detector;
* ``declared_scenario`` never carries marks -- use it for tests of the
  scenario declaration itself, which must hold even for known gaps.
"""

from __future__ import annotations

import pytest

from campaign_detector.scenarios import all_scenarios


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    scenarios = all_scenarios()
    ids = [s.name for s in scenarios]
    if "scenario" in metafunc.fixturenames:
        params = [
            pytest.param(s, marks=[pytest.mark.xfail(strict=True, reason=s.known_gap)] if s.known_gap else [])
            for s in scenarios
        ]
        metafunc.parametrize("scenario", params, ids=ids)
    if "declared_scenario" in metafunc.fixturenames:
        metafunc.parametrize("declared_scenario", scenarios, ids=ids)
