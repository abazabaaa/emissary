# labs

Experiments built on this Emissary checkout. Nothing here changes Emissary itself, and the root Maven build
does not include this folder.

| Folder | What it is |
|---|---|
| [`emissary-places/`](emissary-places/) | Four processing places that turn Emissary's demo pipeline into a basic document pipeline: Tika 4 identification, zip unpacking into child records, Tika 4 text/metadata extraction in crash-isolated forked JVMs, and optional Claude OCR for scans (Anthropic Java SDK). 27 tests, run scripts, a JDK benchmark (OpenJDK vs GraalVM). |
| [`emissary-graph/`](emissary-graph/) | A code + config graph analyzer for this codebase: tree-sitter Java ASTs, Jersey scanning, ServiceLoader, `.cfg` files, test references and git churn, with 12 verified use-case flows and an interactive explorer page. |

## Prerequisites

- JDK 17+ and Maven.
- Emissary built and installed from the repository root: `mvn install -DskipTests`. This installs
  `gov.nsa.emissary:emissary:8.47.0-SNAPSHOT` and its test-jar into `~/.m2`, which `emissary-places` depends on.
- For `emissary-graph`: Python 3 with `tree-sitter`, `tree-sitter-java`, `networkx`.

## Quick start

```bash
cd labs/emissary-places
./setup-config.sh && mvn test        # 27 tests
./run.sh                             # standalone node on :8001; drop files into target/data/InputData
python3 show_output.py               # summarise build/localoutput/json by family

cd ../emissary-graph
python3 analyze.py --repo ../.. --out out && python3 build_page.py   # -> out/explorer.html
```

**Claude OCR is off by default.** When enabled with an Anthropic API key, page images of scanned documents are
sent to Anthropic's API. See `emissary-places/README.md`.
