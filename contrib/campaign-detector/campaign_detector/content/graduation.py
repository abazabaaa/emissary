"""Graduation by identity: a candidate's molecule reappears later elsewhere.

The built-in ``graduation`` evidence only sees a candidate *name* in a later
directory. A molecule that moves on to lead optimisation, a selectivity
campaign or the corporate registry usually changes names (``run_lig029`` ->
``cpd03`` -> ``KDR-0877``), so this index joins on the InChIKey instead.

:class:`GraduationIndex` maps InChIKeys (and their 14-character connectivity
blocks) to :class:`Occurrence` s: ligand identities read from candidates of
detected campaigns (time = that campaign's ``t_start``) and from loose files
outside every candidate such as registry exports (time = file mtime). Its
:meth:`GraduationIndex.hook` backs ``Hooks.graduation``: for each candidate
of a report it emits ``graduation`` evidence for every occurrence that is

* **later**: occurrence time > the report's ``t_end`` (an earlier occurrence
  is where the molecule came from, not where it went);
* **elsewhere**: not inside the report's campaign root;
* **untainted**: no ``NEG_WORDS`` component (``backup``, ``old``...) below its
  common ancestor with the campaign root;
* **not a loose byte copy** of a file of the campaign (that is ``copy_out``
  or a mirror); a copy inside a later campaign's candidate still counts.

Weight is ``strong`` (default 1.0) for a full-key match where both sides
have medium or high confidence, else ``weak`` (0.5; connectivity block only,
or a low-confidence side). Every strong occurrence is emitted; without one,
only the earliest weak occurrence is, so weak matches never add up to the
pick threshold. The detector's coverage cap then drops
re-run-everything campaigns.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ..detect import CampaignReport, DetectionResult, Evidence, EvidenceHook, is_tainted, is_within
from ..inventory import Inventory
from .aggregate import CandidateContent
from .model import LIGAND_ROLES, ReaderResult, candidate_key, confidence_rank, connectivity_block

STRONG_CONFIDENCE = confidence_rank("medium")
"""Both sides of a strong match need at least this confidence rank."""


@dataclass(frozen=True)
class Occurrence:
    """Where and when one molecule was seen.

    ``root``/``candidate_id`` are set when the file belongs to a candidate of
    a detected campaign (``t`` is then the campaign's ``t_start``), ``None``
    for loose files (``t`` is the file's mtime).
    """

    inchikey: str
    inchikey14: str | None
    path: str
    t: int
    root: str | None
    candidate_id: str | None
    confidence: str

    @property
    def where(self) -> str:
        """``root::candidate`` for campaign occurrences, else the path."""
        return candidate_key(self.root, self.candidate_id) if self.root and self.candidate_id else self.path


class GraduationIndex:
    """InChIKey -> occurrences, plus the candidate contents the hook looks up."""

    def __init__(self, contents: Mapping[str, CandidateContent] | None = None) -> None:
        self.contents: Mapping[str, CandidateContent] = contents or {}
        self._by_key: dict[str, list[Occurrence]] = {}
        self._by_block: dict[str, list[Occurrence]] = {}

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_key.values())

    def add(self, occ: Occurrence) -> None:
        """Index one occurrence (duplicates of ``(inchikey, path)`` are ignored)."""
        bucket = self._by_key.setdefault(occ.inchikey, [])
        if any(o.path == occ.path for o in bucket):
            return
        bucket.append(occ)
        bucket.sort(key=lambda o: (o.t, o.path))
        if occ.inchikey14:
            block = self._by_block.setdefault(occ.inchikey14, [])
            block.append(occ)
            block.sort(key=lambda o: (o.t, o.path))

    def lookup(self, inchikey: str, *, skeleton: bool = False) -> list[Occurrence]:
        """Occurrences of ``inchikey``; with ``skeleton`` of its connectivity block (sorted by time)."""
        if skeleton:
            block = connectivity_block(inchikey)
            return list(self._by_block.get(block, ())) if block else []
        return list(self._by_key.get(inchikey, ()))

    @classmethod
    def build(cls, inv: Inventory, result: DetectionResult, contents: Mapping[str, CandidateContent],
              loose: Iterable[ReaderResult]) -> GraduationIndex:
        """Index every candidate identity of ``contents`` and every ligand in ``loose`` results.

        Loose identities whose file is not in ``inv`` are skipped (no time).
        """
        index = cls(contents)
        t_start = {rep.root: rep.t_start for rep in result.campaigns}
        for content in contents.values():
            t = t_start.get(content.root)
            if t is None:
                continue
            for ident in content.identities():
                index.add(Occurrence(ident.inchikey or "", ident.inchikey14 or connectivity_block(ident.inchikey),
                                     ident.source_path, t, content.root, content.candidate_id, ident.confidence))
        for res in loose:
            for lig in res.ligands:
                entry = inv.by_path.get(lig.source_path)
                if lig.role not in LIGAND_ROLES or not lig.inchikey or entry is None:
                    continue
                index.add(Occurrence(lig.inchikey, lig.inchikey14 or connectivity_block(lig.inchikey),
                                     lig.source_path, entry.mtime, None, None, lig.confidence))
        return index

    def evidence(self, inv: Inventory, report: CampaignReport, *, strong: float = 1.0,
                 weak: float = 0.5) -> list[Evidence]:
        """Graduation evidence for the candidates of ``report`` (see the module docstring)."""
        root_shas = {e.sha256 for e in inv.subtree(report.root) if e.kind == "f" and e.sha256}

        def eligible(occ: Occurrence, shas: set[str | None]) -> bool:
            entry = inv.by_path.get(occ.path)
            if entry is None or occ.t <= report.t_end or is_within(occ.path, report.root):
                return False
            if is_tainted(occ.path, report.root):
                return False
            # A loose byte copy of a campaign file is a copy-out or a mirror, not a re-run; a copy
            # placed inside a later campaign's candidate is how a molecule moves on, so it counts.
            return occ.root is not None or entry.sha256 not in shas

        out: list[Evidence] = []
        for cand in report.candidates:
            content = self.contents.get(candidate_key(report.root, cand.id))
            if content is None:
                continue
            best: dict[str, tuple[Occurrence, bool, str]] = {}
            for ident in content.identities():
                key = ident.inchikey or ""
                matches = [(o, True) for o in self.lookup(key)]
                matches += [(o, False) for o in self.lookup(key, skeleton=True) if o.inchikey != key]
                for occ, full in matches:
                    if not eligible(occ, root_shas):
                        continue
                    confident = min(confidence_rank(ident.confidence),
                                    confidence_rank(occ.confidence)) >= STRONG_CONFIDENCE
                    is_strong = full and confident
                    how = "InChIKey" if full else "InChIKey connectivity block"
                    if not confident:
                        how += ", low confidence"
                    if occ.path not in best or (is_strong and not best[occ.path][1]):
                        best[occ.path] = (occ, is_strong, how)
            strong_hits = [best[p] for p in sorted(best) if best[p][1]]
            weak_hits = sorted((h for h in best.values() if not h[1]), key=lambda h: (h[0].t, h[0].path))
            # Weak matches never add up: without a strong match only the earliest weak one counts.
            for occ, is_strong, how in strong_hits or weak_hits[:1]:
                out.append(Evidence("graduation", cand.id, occ.path, f"{occ.inchikey} {occ.where}",
                                    strong if is_strong else weak,
                                    f"ligand identity ({how}) reappears later outside the campaign"))
        return out

    def hook(self, *, strong: float = 1.0, weak: float = 0.5) -> EvidenceHook:
        """A ``Hooks.graduation`` callable backed by this index."""

        def graduation_by_identity(inv: Inventory, report: CampaignReport) -> list[Evidence]:
            return self.evidence(inv, report, strong=strong, weak=weak)

        return graduation_by_identity
