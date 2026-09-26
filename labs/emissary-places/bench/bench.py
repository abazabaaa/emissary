#!/usr/bin/env python3
"""Throughput benchmark: same corpus, same settings, different JDKs.

For each JDK: start a node (OCR off), time start-up, run one warm-up corpus, then time N corpora from the
moment files are dropped until every expected output record exists. CPU is summed over the node JVM and
its Tika fork JVMs (utime+stime from /proc).
Usage: bench.py --jdk label=/path/to/java [--jdk ...] [--files 200] [--runs 2]
"""
import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent.parent
TICK = os.sysconf("SC_CLK_TCK")


def java_pids():
    pids = []
    for p in pathlib.Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            except OSError:
                continue
            if "java" in cmd and (str(HERE) in cmd or "emissary" in cmd) and "bench.py" not in cmd:
                pids.append(int(p.name))
    return pids


def cpu_seconds(pids):
    total = 0
    for pid in pids:
        try:
            f = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
            total += int(f[11]) + int(f[12])  # utime, stime (fields 14, 15)
        except (OSError, IndexError):
            pass
    return total / TICK


def records(outdir):
    n = 0
    if outdir.exists():
        for f in outdir.iterdir():
            if f.is_file() and not f.name.endswith(".bgjournal"):
                for line in f.read_text(errors="replace").splitlines():
                    if line.strip():
                        try:
                            n += len(json.loads(line))
                        except json.JSONDecodeError:
                            pass  # line still being written
    return n


def stop_node():
    for pid in java_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(60):
        if not java_pids():
            return
        time.sleep(1)
    for pid in java_pids():
        os.kill(pid, signal.SIGKILL)


def make_corpus(tag, n):
    d = HERE / "bench" / f"corpus-{tag}"
    shutil.rmtree(d, ignore_errors=True)
    subprocess.run([sys.executable, str(HERE / "samples" / "make_samples.py"), str(d), "--bench", str(n)],
                   check=True, capture_output=True)
    for f in d.iterdir():  # unique names per run so the output never mixes runs
        f.rename(d / f"{tag}-{f.name}")
    return d


def run_jdk(label, java, n, runs):
    stop_node()
    shutil.rmtree(HERE / "build" / "localoutput", ignore_errors=True)
    shutil.rmtree(HERE / "target" / "data", ignore_errors=True)
    log = open(HERE / f"bench-{label}.log", "w")
    t0 = time.time()
    subprocess.Popen(["./run.sh"], cwd=HERE, env={**os.environ, "JAVA": java}, stdout=log, stderr=subprocess.STDOUT)
    while "Started EmissaryServer" not in (HERE / f"bench-{label}.log").read_text(errors="replace"):
        if time.time() - t0 > 180:
            raise SystemExit(f"{label}: node did not start")
        time.sleep(0.25)
    startup = time.time() - t0
    inbox = HERE / "target" / "data" / "InputData"
    out = HERE / "build" / "localoutput" / "json"
    per_corpus = (n // 5) * 3 + (n - n // 5)  # zips yield parent + 2 children

    results = []
    expected = 0
    for i in range(runs + 1):
        corpus = make_corpus(f"{label}{i}", n)
        expected += per_corpus
        pids = java_pids()
        c0, w0 = cpu_seconds(pids), time.time()
        for f in corpus.iterdir():
            shutil.move(str(f), inbox / f.name)
        while records(out) < expected:
            if time.time() - w0 > 900:
                raise SystemExit(f"{label}: timed out at {records(out)}/{expected} records")
            time.sleep(0.2)
        wall = time.time() - w0
        cpu = cpu_seconds(java_pids()) - c0
        kind = "warm-up" if i == 0 else f"run {i}"
        print(f"  {label:10s} {kind:8s} {n} files in {wall:6.2f}s  = {n / wall:6.1f} files/s   cpu {cpu:6.1f}s", flush=True)
        if i > 0:
            results.append((wall, cpu))
    stop_node()
    return startup, results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jdk", action="append", required=True, help="label=/path/to/bin/java")
    ap.add_argument("--files", type=int, default=200)
    ap.add_argument("--runs", type=int, default=2)
    a = ap.parse_args()
    summary = {}
    for spec in a.jdk:
        label, java = spec.split("=", 1)
        print(f"== {label}: {subprocess.run([java, '-version'], capture_output=True, text=True).stderr.splitlines()[-1]}")
        summary[label] = run_jdk(label, java, a.files, a.runs)
    print("\nlabel       startup   files/s (mean of timed runs)   cpu s/run")
    for label, (startup, res) in summary.items():
        wall = sum(r[0] for r in res) / len(res)
        cpu = sum(r[1] for r in res) / len(res)
        print(f"{label:10s} {startup:7.1f}s   {a.files / wall:8.1f}                     {cpu:8.1f}")


if __name__ == "__main__":
    main()
