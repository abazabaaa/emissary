"""Scenario registry.

Each submodule ``<kind>_<group>.py`` defines zero-argument ``build_<short>()``
functions decorated with :func:`register`. The scenario name is
``"<module basename>.<short>"`` so modules written by different people cannot
collide. :func:`all_scenarios` imports every submodule once.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable

from ..inventory import Inventory
from ..synth import ExpectedOutcome, Scenario

_REGISTRY: dict[str, Scenario] = {}
_loaded = False

BuildFn = Callable[[], Inventory]


def register(*, kind: str, description: str, expected: ExpectedOutcome, known_gap: str | None = None,
             name: str | None = None) -> Callable[[BuildFn], BuildFn]:
    """Decorator registering a ``build_<short>()`` function as a :class:`Scenario`.

    ``name`` overrides ``<short>``; the module basename is always prefixed.
    Raises ``ValueError`` for an unknown ``kind`` or a duplicate name.
    """
    if kind not in ("positive", "negative"):
        raise ValueError(f"kind must be 'positive' or 'negative', not {kind!r}")

    def decorate(fn: BuildFn) -> BuildFn:
        module = fn.__module__.rsplit(".", 1)[-1]
        full = f"{module}.{name or fn.__name__.removeprefix('build_')}"
        if full in _REGISTRY:
            raise ValueError(f"duplicate scenario name: {full}")
        _REGISTRY[full] = Scenario(name=full, kind=kind, description=description, build=fn,  # type: ignore[arg-type]
                                   expected=expected, known_gap=known_gap)
        return fn

    return decorate


def all_scenarios() -> list[Scenario]:
    """Every registered scenario sorted by name (imports all submodules once)."""
    global _loaded
    if not _loaded:
        for mod in pkgutil.iter_modules(__path__):
            importlib.import_module(f"{__name__}.{mod.name}")
        _loaded = True
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get(name: str) -> Scenario:
    """The scenario called ``name`` (``KeyError`` if absent)."""
    for s in all_scenarios():
        if s.name == name:
            return s
    raise KeyError(f"unknown scenario: {name}")
