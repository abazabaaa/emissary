# emissary-places

Four processing places for [Emissary](https://github.com/NationalSecurityAgency/emissary) that turn its
demo pipeline into a basic document-processing pipeline: identify files, unpack zips, extract text and
metadata with Apache Tika 4, and optionally OCR scans with Claude. Built as a separate project against
the Emissary jar; the Emissary repository is not modified.

| Place | Stage | Accepts | Does |
|---|---|---|---|
| `TikaIdPlace` | ID (cost 30, after `UnixFilePlace`) | `UNKNOWN` | Tika detection (magic, container, filename) → form such as `ZIP`, `TEXT`, `PDF`, `DOCX`, `IMAGE_PNG`; sets `FILETYPE`, `MIME_TYPE` |
| `UnzipPlace` | TRANSFORM | `ZIP` | One child per entry (`x.zip-att-N`, form `UNKNOWN`, re-identified, nested zips recurse). Parent → `ZIP-UNWRAPPED`, `ZIP-PASSWORD-PROTECTED` or `ZIP-BROKEN`. Entry-count and size limits against zip bombs |
| `TikaTextPlace` | ANALYZE | `*` except `ZIP*`, `UNKNOWN`, `ERROR` | Tika 4 `PipesForkParser`: parsing in forked JVMs, so a crash/OOM/hang kills a fork, not the node. Markdown text → `TEXT` view; `TITLE`, `AUTHOR`, `CREATED`, `MODIFIED`, `PAGE_COUNT`, `LANGUAGE` (ISO 639-3, e.g. `eng`), `TEXT_CHARS` |
| `ClaudeOcrPlace` | ANALYZE (cost 60, after Tika) | images, `PDF` | **Off by default.** OCR via the Anthropic Java SDK for images and for PDFs with < `MIN_CHARS_PER_PAGE` text per page. Text → `OCR_TEXT` view; `OCR_STATUS`, `OCR_DETAIL`, token counts, served model |

## Run

```bash
./setup-config.sh                      # once: merge Emissary's config (EMISSARY_HOME) with ours into build/config
./run.sh                               # standalone node on :8001
cp files... target/data/InputData/     # input
python3 show_output.py                 # summarise build/localoutput/json by family
mvn test                               # 27 tests (after setup-config.sh)
```

`run.sh` builds `build/config` = Emissary's config + `config-overlay/` (our `places.cfg`, class-name inventory,
1-minute JSON roll). Options: `JAVA=/path/to/java`, `AGENTS=8`, `EXTRA_OVERLAY=dir`, `EXTRA_JAVA_OPTS=...`.

### Claude OCR

Enable by setting `OCR_ENABLED = "true"` in a `demo.places.ClaudeOcrPlace.cfg` placed in the config overlay and
exporting `ANTHROPIC_API_KEY` for the node. **When enabled, page images of scanned documents are sent to
Anthropic's API.** Defaults: `claude-opus-5`, effort `medium`, `max_tokens` 16000, 5 pages per request,
server-side refusal fallbacks on (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`).

Every response's `stop_reason` is checked:
- `max_tokens`: the page batch is split in half and re-sent. A single page that still truncates → `TRUNCATED`.
- `refusal`: recorded with its category → `REFUSED`.
- Mixed outcomes across batches → `PARTIAL`.

Inputs are kept inside API limits: PDF requests stay under 20 MB, and images are downscaled to 2576 px on the
long edge or re-encoded as PNG.

`EXTRA_OVERLAY=config-ocr-stub EXTRA_JAVA_OPTS=-Ddemo.ocr.apiKey=x ./run.sh` with `python3 bench/stub_claude.py`
runs the whole OCR path against a local stub that returns a canned, clearly labelled transcription.

Tika 4's own `ClaudeVLMParser` is not used. In 4.0.0 it:
- defaults to the deprecated `claude-sonnet-4-20250514`;
- never reads `stop_reason`, so truncation and refusals are silent;
- sends a whole PDF with `max_tokens` 4096;
- takes the key only as a static config value.

## Notes and gotchas found while building

- **Jetty.** Tika 4's BOM pins Jetty 12, but Emissary's server is Jetty 11. `pom.xml` imports `jetty-bom` 11.0.26
  *before* `tika-bom`; without that the node fails at start (`NoClassDefFoundError ... ContextHandler$Context`).
- **`MultiFileServerPlace.configurePlace()`.** Emissary declares it but never calls it; subclasses must.
- **Config precedence.** The first value of a duplicated key wins. A `<fqcn>.cfg` in the config dir *replaces*
  the classpath copy rather than merging with it.
- **Processing errors in output.** Emissary's JSON output omits processing errors, so the places also write
  reasons to parameters (`OCR_DETAIL`, `TIKA_STATUS`).
- **Image form names.** Emissary's magic identification names images `PNG`/`JPEG`/...; Tika's gives
  `IMAGE_PNG`/...; the OCR place accepts both.
- **Tika forks.** The first parse waits about 5 s for the forked JVM, then parses take about 10 ms. On a 4-core
  host Tika recommends 1 fork (`NUM_FORKS`).

## Layout

```
src/main/java/demo/places/        TikaIdPlace, UnzipPlace, TikaTextPlace, ClaudeOcrPlace, support/TikaForks
src/main/resources/demo/places/   per-place .cfg
src/test/java/demo/places/        tests; OCR tests use a local stub of the Messages API (no network, no spend)
config-overlay/ config-ocr-stub/  config added on top of Emissary's
samples/make_samples.py           demo input set, or --bench N mixed corpus
bench/bench.py                    JDK throughput comparison;  bench/stub_claude.py  local API stub
```

`docs/e2e-output.txt` is the output of one end-to-end run. Its OCR text came from `bench/stub_claude.py` (a local stub),
not from Claude, and is labelled as such.
