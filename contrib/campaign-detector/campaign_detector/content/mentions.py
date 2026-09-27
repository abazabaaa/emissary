"""Text mentions: notes, READMEs, sheets and slides that name a candidate.

:class:`MentionIndex` backs ``Hooks.text_mentions``. A mention counts for a
campaign only when its document sits directly in one of that campaign's
curated directories and is untainted; it then yields one ``text_mention``
evidence per (document, candidate) with a fixed weight per document. A
mention names a candidate by

* ``candidate_id``: shared id tokens (``lig35`` matches ``run_lig035``);
* ``inchikey``: equal to one of the candidate's ligand keys;
* ``compound_id``: equal (case-insensitive) to a ligand's name;
* ``smiles``: equal to a ligand's SMILES (same ``canon`` assumed).

A document naming (nearly) every candidate is an index, not a pick; the
detector's coverage cap drops it.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping

from ..detect import CampaignReport, Evidence, EvidenceHook, is_tainted
from ..features import id_tokens
from ..inventory import Inventory
from .aggregate import CandidateContent
from .model import Mention, ReaderResult, candidate_key


class MentionIndex:
    """Mentions grouped by the directory of their document."""

    def __init__(self, mentions: Iterable[Mention], contents: Mapping[str, CandidateContent] | None = None) -> None:
        self.contents: Mapping[str, CandidateContent] = contents or {}
        self._by_dir: dict[str, list[Mention]] = {}
        for m in sorted(set(mentions), key=lambda m: (m.source_path, m.kind, m.token)):
            self._by_dir.setdefault(posixpath.dirname(m.source_path), []).append(m)

    def __len__(self) -> int:
        return sum(len(v) for v in self._by_dir.values())

    @classmethod
    def from_results(cls, results: Iterable[ReaderResult],
                     contents: Mapping[str, CandidateContent] | None = None) -> MentionIndex:
        """Collect the mentions of every result."""
        return cls((m for r in results for m in r.mentions), contents)

    def _lookup(self, report: CampaignReport) -> dict[tuple[str, str], set[str]]:
        """``(mention kind, normalised token) -> candidate ids`` for identity-based kinds."""
        out: dict[tuple[str, str], set[str]] = {}
        for cand in report.candidates:
            content = self.contents.get(candidate_key(report.root, cand.id))
            for i in content.identities() if content else ():
                for kind, token in (("inchikey", i.inchikey), ("compound_id", (i.name or "").lower() or None),
                                    ("smiles", i.smiles)):
                    if token:
                        out.setdefault((kind, token), set()).add(cand.id)
        return out

    @staticmethod
    def _normalise(kind: str, token: str) -> str:
        token = token.strip()
        return token.upper() if kind == "inchikey" else token.lower() if kind == "compound_id" else token

    def _matches(self, m: Mention, report: CampaignReport, lookup: dict[tuple[str, str], set[str]]) -> list[str]:
        if m.kind != "candidate_id":
            return sorted(lookup.get((m.kind, self._normalise(m.kind, m.token)), ()))
        token = m.token.strip()
        toks = id_tokens(token)
        return [c.id for c in report.candidates if token.lower() == c.id.lower() or toks & id_tokens(c.id)]

    def evidence(self, inv: Inventory, report: CampaignReport, *, weight: float = 0.7) -> list[Evidence]:
        """``text_mention`` evidence for ``report`` from documents in its curated dirs."""
        best: dict[tuple[str, str], Evidence] = {}
        lookup: dict[tuple[str, str], set[str]] | None = None
        for cd in report.curated_dirs:
            for m in self._by_dir.get(cd.path, ()):
                if m.source_path not in inv or is_tainted(m.source_path, report.root):
                    continue
                if lookup is None:
                    lookup = self._lookup(report)
                for cid in self._matches(m, report, lookup):
                    best.setdefault((cid, m.source_path), Evidence(
                        "text_mention", cid, m.source_path, m.token, weight, f"{m.kind} mentioned in text"))
        return [best[k] for k in sorted(best)]

    def hook(self, *, weight: float = 0.7) -> EvidenceHook:
        """A ``Hooks.text_mentions`` callable backed by this index."""

        def text_mentions(inv: Inventory, report: CampaignReport) -> list[Evidence]:
            return self.evidence(inv, report, weight=weight)

        return text_mentions
