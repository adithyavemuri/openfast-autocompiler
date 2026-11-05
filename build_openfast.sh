#!/usr/bin/env bash
# Compatibility launcher. All settings are documented in build-settings.ini;
# the readable build steps are in build_openfast.py. No Bash editing is needed.
set -eu
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
exec python3 "$SCRIPT_DIR/build_openfast.py" "$@"
