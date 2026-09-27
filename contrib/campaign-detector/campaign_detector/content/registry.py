"""Reader dispatch by (engine, format).

A :class:`ReaderRegistry` maps a file format (``FileRef.fmt``; ``"*"`` for
any) and optionally a set of engines to readers. For one file the candidates
are the readers registered for its format and engine whose ``can_read``
accepts it, highest ``priority`` first, then registration order.
:meth:`ReaderRegistry.read_candidate` reads a whole candidate record through
a :class:`~campaign_detector.content.cache.ResultCache`, skipping readers
more expensive than ``max_cost``; a reader that raises yields an empty result
carrying the error (not cached, so a transient license failure is retried).

:class:`StubReader` and :func:`stub_registry` stand in for the licensed
services (OpenEye, Schrodinger, open-source) until they exist: they accept
their formats and return empty results flagged ``stub``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .cache import ResultCache, rebind, ref_key
from .model import CandidateRecord, FileRef, Reader, ReaderResult, cost_rank

ANY_FORMAT = "*"
"""Format wildcard for :meth:`ReaderRegistry.register`."""


@dataclass(frozen=True)
class _Route:
    reader: Reader
    engines: frozenset[str] | None
    priority: int
    order: int


class ReaderRegistry:
    """Readers keyed by format, filtered by engine, ordered by priority."""

    def __init__(self) -> None:
        self._routes: dict[str, list[_Route]] = {}
        self._count = 0

    def register(self, reader: Reader, *, fmts: Iterable[str], engines: Iterable[str] | None = None,
                 priority: int = 0) -> None:
        """Route ``fmts`` (``"*"`` = any) to ``reader``, optionally only for ``engines``.

        A reader registered with ``engines`` is never used for files whose
        engine is unknown (``None``, ``""`` or ``"unknown"``).
        """
        if not isinstance(reader, Reader):
            raise TypeError(f"{reader!r} does not implement the Reader protocol")
        cost_rank(reader.cost)  # validates the declared cost
        eng = frozenset(engines) if engines is not None else None
        for fmt in fmts:
            self._routes.setdefault(fmt, []).append(_Route(reader, eng, priority, self._count))
            self._count += 1

    def readers(self) -> list[Reader]:
        """Every registered reader once, in registration order."""
        seen: dict[int, tuple[int, Reader]] = {}
        for routes in self._routes.values():
            for r in routes:
                seen.setdefault(id(r.reader), (r.order, r.reader))
        return [rd for _, rd in sorted(seen.values(), key=lambda t: t[0])]

    def for_file(self, ref: FileRef, engine: str | None) -> list[Reader]:
        """Readers for ``ref`` in ``engine`` that accept it, best first, each once."""
        known = engine not in (None, "", "unknown")
        routes = self._routes.get(ref.fmt, []) + self._routes.get(ANY_FORMAT, [])
        ok = [r for r in routes if r.engines is None or (known and engine in r.engines)]
        out: list[Reader] = []
        for r in sorted(ok, key=lambda r: (-r.priority, r.order)):
            if all(r.reader is not o for o in out) and r.reader.can_read(ref):
                out.append(r.reader)
        return out

    def read_file(self, ref: FileRef, engine: str | None, *, max_cost: str = "small",
                  cache: ResultCache | None = None) -> list[ReaderResult]:
        """Results of every eligible reader for one file (cached by content)."""
        limit = cost_rank(max_cost)
        out = []
        for reader in self.for_file(ref, engine):
            if cost_rank(reader.cost) > limit:
                continue
            key = ref_key(ref)
            hit = cache.get(key, reader.name, reader.version) if cache is not None else None
            if hit is not None:
                out.append(rebind(hit, ref.path))
                continue
            try:
                res = reader.read(ref)
            except Exception as exc:  # a failing reader must not stop the batch
                out.append(ReaderResult(reader=reader.name, reader_version=reader.version, toolkit="",
                                        toolkit_version="", input_path=ref.path, input_sha256=ref.sha256,
                                        cost=reader.cost, errors=[f"{type(exc).__name__}: {exc}"]))
                continue
            if cache is not None and not res.errors:
                cache.put(res, key=key)
            out.append(res)
        return out

    def read_candidate(self, rec: CandidateRecord, *, max_cost: str = "small",
                       cache: ResultCache | None = None) -> list[ReaderResult]:
        """Results for every file of ``rec`` (files by path, readers by priority)."""
        out = []
        for ref in rec.all_files():
            out.extend(self.read_file(ref, rec.engine, max_cost=max_cost, cache=cache))
        return out


class StubReader:
    """Placeholder for a licensed reader: accepts ``fmts``, returns an empty result flagged ``stub``."""

    def __init__(self, name: str, fmts: Iterable[str], *, toolkit: str, cost: str = "small",
                 license_feature: str | None = None, version: str = "0") -> None:
        self.name = name
        self.version = version
        self.cost = cost
        self.toolkit = toolkit
        self.license_feature = license_feature
        self.fmts = frozenset(fmts)
        self.calls = 0

    def can_read(self, ref: FileRef) -> bool:
        """True for the formats this stub stands in for."""
        return ref.fmt in self.fmts

    def read(self, ref: FileRef) -> ReaderResult:
        """An empty result flagged ``stub`` (no file I/O)."""
        self.calls += 1
        return ReaderResult(reader=self.name, reader_version=self.version, toolkit=self.toolkit,
                            toolkit_version="", input_path=ref.path, input_sha256=ref.sha256, cost=self.cost,
                            license_feature=self.license_feature, flags=["stub"])


STUB_ROUTES: dict[str, tuple[str, str | None, tuple[str, ...]]] = {
    "oe-reader": ("openeye", "OEChem", ("sdf", "mol2", "smi", "pdb", "oeb", "oez", "oedu")),
    "sdgr-reader": ("schrodinger", None, ("mae", "glide.pv", "glide.lib", "desmond.cms", "fep.fmp",
                                                   "maestro.prj", "maestro.prjzip", "desmond.eaf")),
    "oss-reader": ("rdkit+mdanalysis", None, ("amber.prmtop", "amber.mdout", "amber.mdin", "gromacs.edr",
                                              "gromacs.log", "namd.log", "desmond.multisim_log", "csv",
                                              "analysis.series")),
}
"""Which planned service would read which formats: ``name -> (toolkit, license feature, fmts)``.

License feature names are unverified; Schrodinger's is left ``None`` until a pilot measures which
read-only calls check out tokens."""


def stub_registry() -> ReaderRegistry:
    """A registry of :class:`StubReader` s following :data:`STUB_ROUTES`."""
    reg = ReaderRegistry()
    for name, (toolkit, feature, fmts) in STUB_ROUTES.items():
        reg.register(StubReader(name, fmts, toolkit=toolkit, license_feature=feature), fmts=fmts)
    return reg
