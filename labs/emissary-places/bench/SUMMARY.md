# JDK benchmark: OpenJDK 21 vs Oracle GraalVM 21

**Setup:** 4-core container, standalone node, OCR off.
- Corpus: mixed txt / html / pdf / json / zip; 1,000 files and 1,400 output records per run.
- Settings: 250 ms input polling, 4 agents, 2 Tika forks.
- JDKs: OpenJDK 21.0.10 (Ubuntu build, C2 JIT) and Oracle GraalVM 21.0.12 (Graal JIT).
- The same JDK runs both the node and the Tika forks.

| Configuration | Steady state (runs 3-6) | CPU per 1,000 files | Startup |
|---|---|---|---|
| OpenJDK, 4 agents | 256 files/s | ~3.8 s | 4.5 s |
| GraalVM, 4 agents | 266 files/s (+4%) | ~5.1 s | 4.8 s |
| OpenJDK, 8 agents | 279 files/s (+9%) | ~3.8 s | 4.5 s |

- **GraalVM:** slower for the first ~3,000 files while the Graal compiler warms up. It ends ~4% ahead, which is
  within run-to-run noise (about ±5%), and it uses more CPU.
- **At the default 5 s input polling**, both JDKs measured ~31 files/s (polling-bound, not processing-bound).
- **CPU sits at about a quarter of the 4 cores**, so this workload is bounded by pickup queueing and concurrency,
  not code speed.
- **The levers that matter:** polling interval, agent count, Tika fork count for heavy documents, and more
  nodes in cluster mode.
- **GraalVM native-image was not tried.** Emissary loads classes by name from config, Tika 4 forks
  separate `java` processes anyway, and native image mainly improves startup and memory, not the
  sustained throughput a long-running node needs.

Raw output: `results-*.txt`. Reproduce: `EXTRA_OVERLAY=config-bench python3 bench/bench.py --jdk a=/path/java --jdk b=/path/java --files 1000 --runs 6`
