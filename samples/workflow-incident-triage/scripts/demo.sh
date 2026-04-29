#!/usr/bin/env bash
# Pre-flight check + narration for the workflow-incident-triage demo.
#
# Verifies that Azurite, the Functions host, and the workflow tools are
# reachable, then walks the presenter through the M1 stakeholder demo
# one step at a time. The script is interactive (pauses between steps)
# and does NOT drive the chat UI itself — pasting the prompt and
# watching the live-progress card is intentionally a manual step so the
# audience sees the agent author the plan in real time.
#
# This is a presenter aid, not a test. Functional validation lives in
# the pytest suite under tests/.
#
# Usage:
#   ./demo.sh                           # full demo with default settings
#   ./demo.sh --no-browser              # skip auto-opening the chat UI
#   ./demo.sh --skip-pause              # rehearsal mode (no Enter prompts)
#   BASE_URL=http://localhost:7071 ./demo.sh
#
# Requires: bash, curl, awk, and either xdg-open / open / cmd.exe / wslview
# (browser auto-open will degrade gracefully if none is available).

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:7071}"
NO_BROWSER=0
SKIP_PAUSE=0

while (( "$#" )); do
    case "$1" in
        --base-url)        BASE_URL="$2"; shift 2 ;;
        --base-url=*)      BASE_URL="${1#*=}"; shift ;;
        --no-browser)      NO_BROWSER=1; shift ;;
        --skip-pause)      SKIP_PAUSE=1; shift ;;
        -h|--help)         sed -n '1,/^set -e/p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

# ---------- ANSI colors (only on a TTY) ----------

if [ -t 1 ]; then
    C_CYAN=$'\033[36m'
    C_GREEN=$'\033[32m'
    C_RED=$'\033[31m'
    C_YELLOW=$'\033[33m'
    C_GREY=$'\033[90m'
    C_RESET=$'\033[0m'
else
    C_CYAN= C_GREEN= C_RED= C_YELLOW= C_GREY= C_RESET=
fi

write_step() {
    printf '\n%s── %s ──%s\n' "$C_CYAN" "$1" "$C_RESET"
    if [ -n "${2:-}" ]; then printf '%s\n' "$2"; fi
}
write_ok()   { printf '  %s[ok]%s %s\n' "$C_GREEN" "$C_RESET" "$1"; }
write_fail() { printf '  %s[!!]%s %s\n' "$C_RED"   "$C_RESET" "$1"; }
write_note() { printf '       %s%s%s\n' "$C_GREY"  "$1" "$C_RESET"; }

pause_if_interactive() {
    [ "$SKIP_PAUSE" = 1 ] && return 0
    printf '\n'
    # shellcheck disable=SC2162
    read -p "${1:-Press Enter to continue} " _ || true
}

# ---------- pre-flight ----------

write_step "Pre-flight" "Checking that Azurite, the Functions host, and the workflow tools are reachable."

# Azurite TCP probe (no curl on a raw blob endpoint — Azurite returns 400 on /).
if (echo > /dev/tcp/127.0.0.1/10000) >/dev/null 2>&1; then
    write_ok "Azurite blob endpoint reachable (127.0.0.1:10000)"
else
    write_fail "Azurite is not reachable on 127.0.0.1:10000"
    write_note "Start it with:  azurite --silent --location ./.azurite"
    write_note "Durable Functions defaults to Azure Storage, so this is required."
    exit 1
fi

root_status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "$BASE_URL/" 2>/dev/null || true)
root_status="${root_status:-000}"
if [ "$root_status" = "200" ]; then
    write_ok "Functions host serving the chat UI at $BASE_URL/"
else
    write_fail "Cannot reach the Functions host at $BASE_URL/ (status: $root_status)"
    write_note "Start it from the sample's src/ directory with:  func start"
    write_note "Make sure your venv is active in the same shell so the worker"
    write_note "picks up azure-functions-durable. (See sample README.)"
    exit 1
fi

probe_status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "$BASE_URL/agent/workflows" 2>/dev/null || true)
probe_status="${probe_status:-000}"
case "$probe_status" in
    200)
        write_ok "Workflow tools are wired (GET /agent/workflows -> 200)"
        ;;
    404|501)
        write_fail "Workflow capability probe returned $probe_status — workflows are not enabled."
        write_note "Confirm main.agent.md contains 'workflows.enabled: true' and restart func host."
        exit 1
        ;;
    *)
        write_fail "Workflow capability probe returned unexpected status: $probe_status"
        exit 1
        ;;
esac

printf '\n%sPre-flight passed. You are ready to demo.%s\n' "$C_GREEN" "$C_RESET"
pause_if_interactive "Press Enter to start narration"

# ---------- narration ----------

write_step "Step 1 of 5: open the chat UI" "$(cat <<EOF
The chat UI is served by the Functions host itself at:
  $BASE_URL/

It auto-detects whether the agent has workflow tools enabled. When the
session is visible it polls GET /agent/workflows on a 2–5s cadence and
renders a per-workflow live-progress card inline with the chat thread.
EOF
)"

if [ "$NO_BROWSER" = 0 ]; then
    opened=0
    for opener in xdg-open open wslview cmd.exe; do
        if command -v "$opener" >/dev/null 2>&1; then
            if [ "$opener" = "cmd.exe" ]; then
                cmd.exe /c start "$BASE_URL/" >/dev/null 2>&1 && opened=1 && break
            else
                "$opener" "$BASE_URL/" >/dev/null 2>&1 && opened=1 && break
            fi
        fi
    done
    if [ "$opened" = 1 ]; then
        write_note "Opened in your default browser."
    else
        write_note "Could not auto-open the browser. Open $BASE_URL/ manually."
    fi
fi
pause_if_interactive

write_step "Step 2 of 5: paste this prompt" "$(cat <<EOF
Copy the line below into the chat input. The agent will author a five-task
DAG: three parallel fetches, a 30-second durable timer, and a final
summarize step.
EOF
)"
printf '\n'
printf '  %sWe%s%sre seeing latency spikes and intermittent 502s on the orders-api%s\n' "$C_YELLOW" "'" "$C_YELLOW" "$C_RESET"
printf '  %sservice for the last 20 minutes. Pull recent logs, metrics, and the%s\n' "$C_YELLOW" "$C_RESET"
printf '  %sdeploy history in parallel; let in-flight work drain for 30 seconds;%s\n' "$C_YELLOW" "$C_RESET"
printf '  %sthen summarize what you find.%s\n' "$C_YELLOW" "$C_RESET"
pause_if_interactive

write_step "Step 3 of 5: watch the workflow card render" "$(cat <<EOF
Within a few seconds the agent should call start_workflow and a card
should appear in the chat thread. Things to point out:

  * Five tasks: fetch_logs, fetch_metrics, fetch_deploys, cooldown (wait),
    summarize_findings.
  * The three fetches transition to 'running' immediately and 'completed'
    in roughly the same wave — that is real Durable fan-out, not a
    sequential loop.
  * The cooldown wait sits at 'running' for ~30s. This is a durable
    timer: if you killed func.exe right now and restarted it, the timer
    would resume and the workflow would still complete.
EOF
)"
pause_if_interactive

write_step "Step 4 of 5: terminal state lands automatically" "$(cat <<EOF
Around the 35-second mark the card should flip to 'Completed' and the
final summarize_findings result should appear inline. The agent did not
have to poll for completion — it ended its turn after start_workflow
returned. The chat UI is what's polling the workflow on a 2–5s cadence;
the agent itself stays out of the loop until the user asks a follow-up.

Things to call out for stakeholders:

  * Token cost: the agent only saw the FINAL summary (and only if the
    user asks for it), not every fetch output, because templating
    happened inside the orchestrator. This is Anthropic-style
    programmatic tool calling with durability.
  * Observability: the same status envelope the UI polls is also
    available outside the chat via get_workflow_status — operator
    dashboards, on-call tooling, and MCP Tasks clients all read the
    same shape.
EOF
)"
pause_if_interactive

write_step "Step 5 of 5 (optional): demo cooperative cancel" "$(cat <<EOF
If you have time, run the demo a second time and during the 30-second
wait, send a follow-up message:

  actually cancel that

The agent should call cancel_workflow. The orchestration unwinds at the
next wave boundary, the live card flips to 'Canceled', and partial
results gathered before the cancel are still visible. Contrast this with
terminate_workflow, which would stop abruptly and not push back a
completion envelope.
EOF
)"

printf '\n%sDemo dry-run complete.%s\n' "$C_GREEN" "$C_RESET"
write_note "If anything was wrong, fix it now and re-run this script before the live demo."
write_note "To clean up stale workflows between rehearsals, restart func.exe; the per-session"
write_note "owner key changes when the chat UI generates a new session, so old runs are hidden."
