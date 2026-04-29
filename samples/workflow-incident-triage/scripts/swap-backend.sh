#!/usr/bin/env bash
# Swap the workflow-incident-triage sample between Durable Functions
# backends.
#
# The Functions host reads the live host.json. To run the sample on a
# different Durable backend, the right host.json variant must be in
# place when `func start` boots. This script swaps in the canonical
# variant for the requested backend; no in-place editing.
#
# Backends:
#   storage   - classic Azure Storage / Azurite (the committed default)
#   dts       - Durable Task Scheduler (host.dts.json + DTS app settings)
#
# Usage:
#   ./swap-backend.sh storage            # restore the Azure Storage host.json
#   ./swap-backend.sh dts                # use the DTS host.json variant
#   ./swap-backend.sh --status           # show the currently-active backend
#
# The DTS path also reminds you to copy local.settings.dts.json.template
# to local.settings.json (or merge the new keys in) and to start the DTS
# emulator. See the sample README for the full setup.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SRC_DIR="$( cd "$SCRIPT_DIR/../src" && pwd )"

if [ -t 1 ]; then
    C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'; C_GREY=$'\033[90m'; C_RESET=$'\033[0m'
else
    C_CYAN= C_GREEN= C_RED= C_YELLOW= C_GREY= C_RESET=
fi

# Detect which backend is currently active by inspecting host.json for
# the DTS storageProvider type. Defaults to "storage" when ambiguous.
detect_backend() {
    if [ ! -f "$SRC_DIR/host.json" ]; then
        echo "missing"
        return
    fi
    if grep -q '"type"[[:space:]]*:[[:space:]]*"azureManaged"' "$SRC_DIR/host.json"; then
        echo "dts"
    else
        echo "storage"
    fi
}

show_status() {
    local backend
    backend="$( detect_backend )"
    case "$backend" in
        storage) echo "${C_GREEN}storage${C_RESET}  (Azure Storage / Azurite — host.json default)" ;;
        dts)     echo "${C_CYAN}dts${C_RESET}      (Durable Task Scheduler — host.dts.json applied)" ;;
        missing) echo "${C_RED}missing${C_RESET}  (host.json not found in $SRC_DIR — run swap-backend.sh storage|dts)" ;;
        *)       echo "$backend" ;;
    esac
}

usage() {
    cat <<'USAGE'
swap-backend.sh — switch the workflow-incident-triage sample between
Durable Functions backends.

Usage:
    ./swap-backend.sh storage         restore the Azure Storage host.json
    ./swap-backend.sh dts             apply the DTS host.json variant
    ./swap-backend.sh --status        show the currently-active backend
    ./swap-backend.sh --help, -h      show this message

Backends:
    storage   classic Azure Storage / Azurite (the committed default)
    dts       Durable Task Scheduler (host.dts.json + DTS app settings)

The DTS path also reminds you to copy local.settings.dts.json.template
to local.settings.json (or merge the new keys in) and to start the DTS
emulator. See the sample README for the full setup.
USAGE
}

if [ "$#" -eq 0 ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    usage
    echo
    echo "current backend: $( show_status )"
    exit 0
fi

if [ "$1" = "--status" ]; then
    echo "current backend: $( show_status )"
    exit 0
fi

target="$1"

case "$target" in
    storage)
        # Restore the committed default. host.json is always-tracked,
        # so `git checkout HEAD -- host.json` is the canonical undo.
        # We use `HEAD --` (not bare `--`) so the restore is from the
        # last commit, not the index — otherwise a contributor who
        # accidentally staged a swapped host.json would have storage
        # silently no-op while claiming success.
        if ! git -C "$SRC_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
            echo "${C_RED}error:${C_RESET} not inside a git work tree; cannot restore the storage host.json this way." >&2
            echo "  remediation: re-clone the sample, or commit the storage host.json yourself before swapping back." >&2
            exit 1
        fi
        git -C "$SRC_DIR" checkout HEAD -- host.json
        echo "${C_GREEN}OK${C_RESET}  switched to ${C_GREEN}storage${C_RESET} (host.json restored from HEAD)"
        echo "${C_GREY}    don't forget: Azurite must be running (or AzureWebJobsStorage must point at a real Storage account).${C_RESET}"
        ;;
    dts)
        if [ ! -f "$SRC_DIR/host.dts.json" ]; then
            echo "${C_RED}error:${C_RESET} $SRC_DIR/host.dts.json not found" >&2
            exit 1
        fi
        cp "$SRC_DIR/host.dts.json" "$SRC_DIR/host.json"
        echo "${C_GREEN}OK${C_RESET}  switched to ${C_CYAN}dts${C_RESET} (host.dts.json copied to host.json)"
        echo "${C_GREY}    next:${C_RESET}"
        echo "${C_GREY}      1. start the DTS emulator:${C_RESET}"
        echo "${C_GREY}         docker run -d --name dts-emulator -p 8080:8080 -p 8082:8082 \\${C_RESET}"
        echo "${C_GREY}             -e DTS_USE_DYNAMIC_TASK_HUBS=true \\${C_RESET}"
        echo "${C_GREY}             mcr.microsoft.com/dts/dts-emulator:latest${C_RESET}"
        echo "${C_GREY}      2. ensure local.settings.json has DURABLE_TASK_SCHEDULER_CONNECTION_STRING and TASKHUB_NAME${C_RESET}"
        echo "${C_GREY}         (see local.settings.dts.json.template)${C_RESET}"
        echo "${C_GREY}      3. Azurite still needs to be running — AzureWebJobsStorage is required by the Functions runtime regardless of Durable backend${C_RESET}"
        echo "${C_GREY}      4. open the dashboard at http://localhost:8082${C_RESET}"
        echo "${C_GREY}      to swap back: ./scripts/swap-backend.sh storage${C_RESET}"
        ;;
    *)
        echo "${C_RED}error:${C_RESET} unknown backend '$target' (expected: storage | dts)" >&2
        exit 2
        ;;
esac
