"""Every registered scenario: detector output matches the declared expectation."""

from __future__ import annotations

from campaign_detector.detect import detect
from campaign_detector.scenarios import all_scenarios, get
from campaign_detector.synth import Scenario, compare


def test_detector_matches_expectation(scenario: Scenario) -> None:
    result = detect(scenario.build())
    assert compare(scenario.expected, result) == []
    picked = [r.picked() for r in result.campaigns]
    if scenario.kind == "negative":
        assert all(not p for p in picked)
    else:
        assert any(picked)


def test_declaration_is_consistent(declared_scenario: Scenario) -> None:
    s = declared_scenario
    module = s.build.__module__.rsplit(".", 1)[-1]
    assert s.name.startswith(module + ".")
    assert module.startswith(s.kind + "_")
    has_picks = any(s.expected.picked.values())
    assert has_picks == (s.kind == "positive")
    if s.known_gap:
        assert ":" in s.known_gap, "known_gap must read '<heuristic>: <why>'"


def test_registry_is_idempotent_and_sorted() -> None:
    names = [s.name for s in all_scenarios()]
    assert names == sorted(names)
    assert names == [s.name for s in all_scenarios()]
    assert get(names[0]).name == names[0]


def test_builds_are_small_and_deterministic(declared_scenario: Scenario) -> None:
    a, b = declared_scenario.build(), declared_scenario.build()
    assert len(a) < 5000
    assert list(a) == list(b)
