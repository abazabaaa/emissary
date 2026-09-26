"""Command line: ``python -m campaign_detector <subcommand> [options]``.

Subcommands live in :data:`SUBCOMMANDS`; each takes its argument list and
returns an exit code, so adding one is a function plus one dict entry.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Callable, Sequence

from .detect import CampaignReport, DetectionResult, Params, detect
from .features import all_features
from .inventory import Inventory
from .scenarios import all_scenarios, get
from .synth import ExpectedOutcome, compare


def _stamp(ts: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def cmd_synth(argv: Sequence[str]) -> int:
    """``synth --scenario NAME --out FILE`` writes a scenario inventory; ``synth --list`` lists scenarios."""
    ap = argparse.ArgumentParser(prog="campaign_detector synth", description=cmd_synth.__doc__)
    ap.add_argument("--scenario", help="scenario name (see --list)")
    ap.add_argument("--out", help="output TSV path")
    ap.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = ap.parse_args(argv)
    if args.list:
        for s in all_scenarios():
            gap = f"  [known gap: {s.known_gap}]" if s.known_gap else ""
            print(f"{s.name}\t{s.kind}\t{s.description}{gap}")
        return 0
    if not (args.scenario and args.out):
        ap.error("--scenario and --out are required unless --list is given")
    get(args.scenario).build().to_tsv(args.out)
    return 0


def format_report(report: CampaignReport) -> str:
    """Multi-line text rendering of one campaign report."""
    lines = [
        f"campaign {report.root}",
        f"  engine {report.engine}  era {report.era}  template {report.template}  "
        f"candidates {report.n_candidates}  uniformity {report.uniformity:.2f}  confidence {report.confidence:.2f}",
        f"  submitter uid {report.submitter_uid}  chunks {_stamp(report.t_start)} .. {_stamp(report.t_end)} UTC",
        f"  curated dirs ({len(report.curated_dirs)}):",
    ]
    for cd in report.curated_dirs:
        lines.append(f"    {cd.path}  uid {cd.uid}  score {cd.score}  entries {cd.n_files}")
        lines.append(f"      {'; '.join(cd.reasons)}")
    lines.append(f"  selection: picked {len(report.picked())}  not_picked {len(report.not_picked())}  "
                 f"unknown {len(report.unknown())}  (selection confidence {report.selection_confidence:.2f})")
    for c in report.candidates:
        if c.label == "picked":
            lines.append(f"    picked {c.id}  score {c.score:.2f}")
            for e in c.evidence:
                lines.append(f"      {e.kind:<12} {e.src} -> {e.ref}  (w={e.weight})")
    lines.append(f"  missing ids: {', '.join(report.missing_ids) or '-'}")
    lines.append("  notes:" if report.notes else "  notes: -")
    lines.extend(f"    - {n}" for n in report.notes)
    return "\n".join(lines)


def cmd_detect(argv: Sequence[str]) -> int:
    """``detect --inventory FILE [--json] [--tz-offset S]`` runs the detector on a TSV inventory."""
    ap = argparse.ArgumentParser(prog="campaign_detector detect", description=cmd_detect.__doc__)
    ap.add_argument("--inventory", required=True, help="inventory TSV")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    ap.add_argument("--tz-offset", type=int, default=0, help="seconds east of UTC for working-hours features")
    args = ap.parse_args(argv)
    result = detect(Inventory.from_tsv(args.inventory), params=Params(tz_offset_s=args.tz_offset))
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    elif not result.campaigns:
        print("no campaign detected")
    else:
        print("\n\n".join(format_report(r) for r in result.campaigns))
    return 0


def cmd_features(argv: Sequence[str]) -> int:
    """``features --inventory FILE --out FILE.tsv`` writes one row of scalar features per directory."""
    ap = argparse.ArgumentParser(prog="campaign_detector features", description=cmd_features.__doc__)
    ap.add_argument("--inventory", required=True, help="inventory TSV")
    ap.add_argument("--out", required=True, help="output TSV path")
    args = ap.parse_args(argv)
    feats = all_features(Inventory.from_tsv(args.inventory))
    rows = [dataclasses.asdict(f) for f in feats.values()]
    cols = [k for k, v in rows[0].items() if not isinstance(v, (dict, tuple, frozenset))] if rows else []
    with open(args.out, "w", encoding="utf-8", errors="surrogateescape", newline="") as fh:
        fh.write("\t".join(cols) + "\n")
        for row in rows:
            fh.write("\t".join(_cell(row[c]) for c in cols) + "\n")
    return 0


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _describe_expected(exp: ExpectedOutcome) -> str:
    if not exp.campaign_roots:
        return "no campaign"
    picked = sum(len(v) for v in exp.picked.values())
    rest = ",".join(sorted(set(exp.rest.values())))
    return f"{len(exp.campaign_roots)} campaign; picked {picked}" + (f" (rest {rest})" if rest else "")


def _describe_result(result: DetectionResult) -> str:
    if not result.campaigns:
        return "no campaign"
    picked = sum(len(r.picked()) for r in result.campaigns)
    not_picked = sum(len(r.not_picked()) for r in result.campaigns)
    unknown = sum(len(r.unknown()) for r in result.campaigns)
    return f"{len(result.campaigns)} campaign; picked {picked}, not {not_picked}, unknown {unknown}"


def cmd_demo(argv: Sequence[str]) -> int:
    """``demo [--json]`` runs every scenario; exits 1 on any FAIL or XPASS."""
    ap = argparse.ArgumentParser(prog="campaign_detector demo", description=cmd_demo.__doc__)
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    args = ap.parse_args(argv)
    rows = []
    for s in all_scenarios():
        try:
            result = detect(s.build())
            mismatches = compare(s.expected, result)
            got = _describe_result(result)
        except Exception as exc:  # a crashing scenario is reported, not fatal to the demo
            mismatches, got = [f"error: {exc!r}"], "error"
        if s.known_gap:
            status = "XFAIL" if mismatches else "XPASS"
        else:
            status = "FAIL" if mismatches else "PASS"
        rows.append({"scenario": s.name, "kind": s.kind, "expected": _describe_expected(s.expected), "got": got,
                     "status": status, "mismatches": mismatches, "known_gap": s.known_gap})
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows)
    return 1 if any(r["status"] in ("FAIL", "XPASS") for r in rows) else 0


def cmd_materialize(argv: Sequence[str]) -> int:
    """``materialize --scenario NAME --dest DIR [--no-sparse]`` writes a scenario tree to disk plus DIR.owners.tsv."""
    from .walker import materialize

    ap = argparse.ArgumentParser(prog="campaign_detector materialize", description=cmd_materialize.__doc__)
    ap.add_argument("--scenario", required=True, help="scenario name (see synth --list)")
    ap.add_argument("--dest", required=True, help="missing or empty directory; the inventory's / maps to it")
    ap.add_argument("--no-sparse", action="store_true", help="write real bytes (files up to 64 MiB only)")
    args = ap.parse_args(argv)
    try:
        inv = get(args.scenario).build()
        man = materialize(inv, args.dest, sparse=not args.no_sparse)
    except (KeyError, OSError, ValueError) as exc:
        print(f"materialize: {exc}", file=sys.stderr)
        return 1
    apparent = sum(e.size for e in inv.files())
    print(f"materialized {len(inv)} entries ({apparent:,} bytes apparent) under {man.dest}")
    print(f"owners sidecar: {man.sidecar}")
    print(f"walk it back: python -m campaign_detector walk --root {man.dest} --out OUT.tsv "
          f"--map-root {man.dest}:/ --owners {man.sidecar}")
    return 0


def cmd_walk(argv: Sequence[str]) -> int:
    """``walk --root DIR --out FILE.tsv [--map-root SRC:DST] [--hash] [--owners FILE]`` crawls a real tree."""
    from .walker import walk_fs

    ap = argparse.ArgumentParser(prog="campaign_detector walk", description=cmd_walk.__doc__)
    ap.add_argument("--root", required=True, help="directory to crawl (symlinks are never followed below it)")
    ap.add_argument("--out", required=True, help="output inventory TSV")
    ap.add_argument("--map-root", metavar="SRC:DST", help="rewrite on-disk prefix SRC to inventory path DST")
    ap.add_argument("--hash", action="store_true", help="sha256 every regular file (reads sparse files in full)")
    ap.add_argument("--owners", help="owners sidecar TSV (from materialize) overriding uid/gid/ctime/sha256")
    args = ap.parse_args(argv)
    map_root = None
    if args.map_root:
        src, sep, dst = args.map_root.rpartition(":")
        if not (sep and src and dst.startswith("/")):
            ap.error("--map-root must look like SRC:DST with an absolute DST, e.g. /tmp/kdr_fs:/")
        map_root = (src, dst)
    try:
        inv = walk_fs(args.root, map_root=map_root, hash=args.hash, owners=args.owners)
        inv.to_tsv(args.out)
    except (OSError, ValueError) as exc:
        print(f"walk: {exc}", file=sys.stderr)
        return 1
    errors: list[str] = getattr(inv, "walk_errors", [])
    for msg in errors:
        print(f"walk: skipped {msg}", file=sys.stderr)
    print(f"walked {len(inv)} entries into {args.out}" + (f" ({len(errors)} errors)" if errors else ""))
    return 1 if errors else 0


def _print_table(rows: list[dict[str, object]]) -> None:
    cols = ("scenario", "kind", "expected", "got", "status")
    widths = {c: max([len(c)] + [len(str(r[c])) for r in rows]) for c in cols}
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols).rstrip())
        if r["status"] in ("FAIL", "XFAIL"):
            for m in r["mismatches"]:  # type: ignore[attr-defined]
                print(f"    {m}")
        if r["status"] == "XFAIL":
            print(f"    known gap: {r['known_gap']}")
        if r["status"] == "XPASS":
            print("    matches expectation: remove known_gap")
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("PASS", "FAIL", "XFAIL", "XPASS")}
    print(f"\n{len(rows)} scenarios: " + ", ".join(f"{n} {s}" for s, n in counts.items()))


SUBCOMMANDS: dict[str, Callable[[Sequence[str]], int]] = {
    "synth": cmd_synth,
    "detect": cmd_detect,
    "features": cmd_features,
    "demo": cmd_demo,
    "materialize": cmd_materialize,
    "walk": cmd_walk,
}
"""Subcommand name -> handler taking the remaining argv and returning an exit code."""


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch ``argv`` (default ``sys.argv[1:]``) to a subcommand; returns the exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] not in SUBCOMMANDS:
        print("usage: python -m campaign_detector {" + ",".join(SUBCOMMANDS) + "} [options]", file=sys.stderr)
        for name, fn in SUBCOMMANDS.items():
            print(f"  {name:<9} {(fn.__doc__ or '').strip()}", file=sys.stderr)
        return 0 if args[:1] in (["-h"], ["--help"]) else 2
    return SUBCOMMANDS[args[0]](args[1:])
