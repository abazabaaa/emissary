#!/usr/bin/env bash
# Build ./build/config = Emissary's runtime config + our overlay. One directory, because
# Emissary's @{CONFIG_DIR} expansion breaks with several config dirs.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# Emissary checkout, built with `mvn install -DskipTests`. Default: this repository (labs/ lives inside it).
EMISSARY_HOME="${EMISSARY_HOME:-$HERE/../..}"
if [ ! -d "$EMISSARY_HOME/target/config" ]; then
  echo "Emissary config not found at $EMISSARY_HOME/target/config." >&2
  echo "Build Emissary first (mvn install -DskipTests) and/or set EMISSARY_HOME." >&2
  exit 1
fi
rm -rf "$HERE/build/config"
mkdir -p "$HERE/build/config"
cp -r "$EMISSARY_HOME/target/config/." "$HERE/build/config/"
cp -r "$HERE/config-overlay/." "$HERE/build/config/"
# Optional second overlay, e.g. EXTRA_OVERLAY=config-ocr-stub for the OCR demo against a local stub
if [ -n "${EXTRA_OVERLAY:-}" ]; then cp -r "$HERE/$EXTRA_OVERLAY/." "$HERE/build/config/"; fi
echo "config ready: $HERE/build/config"
