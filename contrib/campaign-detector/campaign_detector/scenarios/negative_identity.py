"""Identity negatives: a shared InChIKey that is *not* a graduation.

Each scenario lays down the KDR 2011 FEP campaign of
``positive_identity_graduation`` (identities in every run, curated
``analysis/`` with no picks) plus a place where KDR ligands' InChIKeys
reappear. None of them is a pick, with or without content readers, so the
registry expectation is also the ``detect_with_content`` expectation
(``tests/test_content_pipeline.py`` runs both):

* ``rerun_all``: in 2014 uid 2005 re-runs *every* KDR ligand under new names
  (``/vol6/projects/KDR_rerun_2014/md/cpd01..cpd46``). Every KDR candidate
  gets identity graduation evidence, so the coverage cap drops it all.
* ``in_backup``: the keys of lig012 and lig029 reappear later only under
  ``/vol7/backup/...`` and ``.../ABL_2013/bak/``: tainted, never evidence.
  An untainted later registry export holds an unrelated molecule (control).
* ``earlier``: the keys of lig001..lig008 were first simulated in a 2009
  pilot campaign (``/vol2/projects/KDR_pilot_2009/md``) and lig029's in a
  2009 docking hit list. Earlier occurrences are origins, not graduations,
  for KDR 2011; for the pilot, *all* its compounds reappear in KDR 2011, so
  the coverage cap drops that graduation evidence too.
"""

from __future__ import annotations

from ..content.sidecar import SidecarBuilder
from ..inventory import Inventory
from ..synth import CampaignSpec, ExpectedOutcome, TreeBuilder, at
from . import register
from .positive_identity_graduation import (
    KDR_ROOT, KDR_SPEC, WEEK, kdr_campaign, kdr_compound, kdr_smiles, ligand_campaign, merge, other_smiles,
)

KDR_INDICES: tuple[int, ...] = tuple(i for i in range(1, KDR_SPEC.n_candidates + 1) if i not in KDR_SPEC.skip)
"""The 46 KDR ligands that ran."""

RERUN_ROOT = "/vol6/projects/KDR_rerun_2014/md"
RERUN_SPEC = CampaignSpec(
    engine="amber", n_candidates=len(KDR_INDICES), candidate_fmt="cpd{:02d}", n_chunks=4,
    chunk_interval_s=6 * 3600, chunk_size=1_500_000_000, uid=2005, stagger_s=600, start=at(7 * (WEEK + 160), 1),
)
"""2014 re-run of all 46 KDR ligands (cpd j = the j-th KDR ligand that ran)."""

PILOT_ROOT = "/vol2/projects/KDR_pilot_2009/md"
PILOT_SPEC = CampaignSpec(
    engine="amber", n_candidates=8, candidate_fmt="cpd{:02d}", n_chunks=8, chunk_interval_s=6 * 3600,
    chunk_size=800_000_000, uid=2001, start=at(7 * (WEEK - 104), 4),
)
"""2009 pilot: cpd j is KDR lig00j (all eight are in the 2011 campaign)."""


def _base() -> tuple[TreeBuilder, SidecarBuilder]:
    tb = TreeBuilder(root="/vol3")
    sb = SidecarBuilder()
    kdr_campaign(tb, sb)
    return tb, sb


def _rerun_all() -> tuple[TreeBuilder, SidecarBuilder]:
    tb, sb = _base()
    ligand_campaign(tb, sb, RERUN_ROOT, RERUN_SPEC, lambda j: kdr_smiles(KDR_INDICES[j - 1]),
                    name_of=lambda j: kdr_compound(KDR_INDICES[j - 1]))
    return tb, sb


def _in_backup() -> tuple[TreeBuilder, SidecarBuilder]:
    tb, sb = _base()
    later = at(7 * (WEEK + 110), 11)
    backup = tb.file("/vol7/backup/registry_2013/kdr_nominations.sdf", size=24_000, mtime=later, uid=3002)
    stash = tb.file("/vol5/projects/ABL_2013/bak/from_kdr.sdf", size=9_000, mtime=later + 3600, uid=2005)
    for n, i in enumerate((12, 29)):
        sb.ligand(backup, kdr_smiles(i), name=kdr_compound(i), record=str(n + 1))
    sb.ligand(stash, kdr_smiles(29), name=kdr_compound(29))
    control = tb.file("/vol9/registry/exports/nominations_2013.sdf", size=8_000, mtime=later, uid=3002)
    sb.ligand(control, other_smiles("reg", 7), name="REG-0007")
    return tb, sb


def _earlier() -> tuple[TreeBuilder, SidecarBuilder]:
    tb, sb = _base()
    ligand_campaign(tb, sb, PILOT_ROOT, PILOT_SPEC, kdr_smiles, name_of=kdr_compound)
    hits = tb.file("/vol2/docking/KDR_2009/fred_hits.sdf", size=30_000, mtime=at(7 * (WEEK - 110), 15), uid=2001)
    sb.ligand(hits, kdr_smiles(29), name=kdr_compound(29), confidence="medium")
    return tb, sb


CONTENT = {
    "rerun_all": lambda: _rerun_all()[1],
    "in_backup": lambda: _in_backup()[1],
    "earlier": lambda: _earlier()[1],
}
"""Sidecar content per scenario short name (read by ``content.sidecar.content_for``)."""

_KDR_NONE = ExpectedOutcome.campaign_no_selection(KDR_ROOT, ["run_lig029"])


@register(
    kind="negative",
    description="every KDR ligand's InChIKey reappears in a 2014 re-run campaign: coverage cap, no graduation picks",
    expected=merge(_KDR_NONE, ExpectedOutcome.campaign_no_selection(RERUN_ROOT)),
)
def build_rerun_all() -> Inventory:
    """Build KDR 2011 plus the 2014 re-run of all its ligands."""
    return _rerun_all()[0].build()


@register(
    kind="negative",
    description="lig012/lig029 InChIKeys reappear later only under backup/ and bak/ paths: tainted, no evidence",
    expected=_KDR_NONE,
)
def build_in_backup() -> Inventory:
    """Build KDR 2011 plus later backup copies of registry nominations."""
    return _in_backup()[0].build()


@register(
    kind="negative",
    description="KDR ligand keys occur in an EARLIER 2009 pilot campaign and docking list: origins, not graduation",
    expected=merge(_KDR_NONE, ExpectedOutcome.campaign_no_selection(PILOT_ROOT)),
)
def build_earlier() -> Inventory:
    """Build the 2009 pilot, a 2009 docking hit list and KDR 2011."""
    return _earlier()[0].build()
