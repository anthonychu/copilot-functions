<#
.SYNOPSIS
    Pre-flight check + narration for the workflow-incident-triage demo.

.DESCRIPTION
    Verifies that Azurite, the Functions host, and the workflow tools are
    reachable, then walks the presenter through the M1 stakeholder demo
    one step at a time. The script is interactive (presses pause between
    steps) and does NOT drive the chat UI itself — pasting the prompt
    and watching the live-progress card is intentionally a manual step
    so the audience sees the agent author the plan in real time.

    This is a presenter aid, not a test. Functional validation lives in
    the pytest suite under ``tests/``.

.PARAMETER BaseUrl
    Base URL of the running Functions host. Defaults to
    http://localhost:7071.

.PARAMETER NoBrowser
    Skip auto-opening the chat UI in the default browser.

.PARAMETER SkipPause
    Run all steps without waiting for Enter between them. Useful when
    rehearsing or when re-running pre-flight only.

.EXAMPLE
    .\demo.ps1
    Run the full demo dry-run with default settings.

.EXAMPLE
    .\demo.ps1 -BaseUrl http://localhost:7071 -NoBrowser
    Pre-flight + narration only; do not open a browser.
#>

[CmdletBinding()]
param(
    [string]$BaseUrl = "http://localhost:7071",
    [switch]$NoBrowser,
    [switch]$SkipPause
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step {
    param([string]$Title, [string]$Body)
    Write-Host ""
    Write-Host "── $Title ──" -ForegroundColor Cyan
    if ($Body) { Write-Host $Body }
}

function Write-Ok {
    param([string]$Message)
    Write-Host "  [ok] $Message" -ForegroundColor Green
}

function Write-Fail {
    param([string]$Message)
    Write-Host "  [!!] $Message" -ForegroundColor Red
}

function Write-Note {
    param([string]$Message)
    Write-Host "       $Message" -ForegroundColor DarkGray
}

function Pause-If-Interactive {
    param([string]$Prompt = "Press Enter to continue")
    if ($SkipPause) { return }
    Write-Host ""
    Read-Host -Prompt $Prompt | Out-Null
}

function Test-Tcp {
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 1500)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# ---------- pre-flight ----------

Write-Step -Title "Pre-flight" -Body "Checking that Azurite, the Functions host, and the workflow tools are reachable."

$azuriteOk = Test-Tcp -HostName "127.0.0.1" -Port 10000
if ($azuriteOk) {
    Write-Ok "Azurite blob endpoint reachable (127.0.0.1:10000)"
} else {
    Write-Fail "Azurite is not reachable on 127.0.0.1:10000"
    Write-Note "Start it with:  azurite --silent --location ./.azurite"
    Write-Note "Durable Functions defaults to Azure Storage, so this is required."
    exit 1
}

try {
    $rootResp = Invoke-WebRequest -Uri "$BaseUrl/" -Method Get -TimeoutSec 4 -UseBasicParsing
    if ($rootResp.StatusCode -eq 200) {
        Write-Ok "Functions host serving the chat UI at $BaseUrl/"
    } else {
        Write-Fail "Unexpected status from $BaseUrl/ : $($rootResp.StatusCode)"
        exit 1
    }
} catch {
    Write-Fail "Cannot reach the Functions host at $BaseUrl/"
    Write-Note "Start it from the sample's src/ directory with:  func start"
    Write-Note "Make sure your venv is active in the same shell so the worker"
    Write-Note "picks up azure-functions-durable. (See sample README.)"
    exit 1
}

try {
    $probe = Invoke-WebRequest -Uri "$BaseUrl/agent/workflows" -Method Get -TimeoutSec 4 -UseBasicParsing -ErrorAction Stop
    if ($probe.StatusCode -eq 200) {
        Write-Ok "Workflow tools are wired (GET /agent/workflows -> 200)"
    } else {
        Write-Fail "Workflow capability probe returned status $($probe.StatusCode)"
        Write-Note "Expected 200. If you get 404/501, workflows.enabled is not set in main.agent.md."
        exit 1
    }
} catch {
    $status = $_.Exception.Response.StatusCode.value__
    if ($status -eq 404 -or $status -eq 501) {
        Write-Fail "Workflow capability probe returned $status — workflows are not enabled."
        Write-Note "Confirm main.agent.md contains 'workflows.enabled: true' and restart func host."
    } else {
        Write-Fail "Workflow capability probe failed: $($_.Exception.Message)"
    }
    exit 1
}

Write-Host ""
Write-Host "Pre-flight passed. You are ready to demo." -ForegroundColor Green
Pause-If-Interactive -Prompt "Press Enter to start narration"

# ---------- narration ----------

Write-Step -Title "Step 1 of 5: open the chat UI" -Body @"
The chat UI is served by the Functions host itself at:
  $BaseUrl/

It auto-detects whether the agent has workflow tools enabled. When the
session is visible it polls GET /agent/workflows on a 2–5s cadence and
renders a per-workflow live-progress card inline with the chat thread.
"@
if (-not $NoBrowser) {
    try {
        Start-Process "$BaseUrl/" | Out-Null
        Write-Note "Opened in your default browser."
    } catch {
        Write-Note "Could not auto-open the browser. Open $BaseUrl/ manually."
    }
}
Pause-If-Interactive

Write-Step -Title "Step 2 of 5: paste this prompt" -Body @"
Copy the line below into the chat input. The agent will author a five-task
DAG: three parallel fetches, a 30-second durable timer, and a final
summarize step.
"@
Write-Host ""
Write-Host '  We''re seeing latency spikes and intermittent 502s on the orders-api ' -ForegroundColor Yellow
Write-Host '  service for the last 20 minutes. Pull recent logs, metrics, and the   ' -ForegroundColor Yellow
Write-Host '  deploy history in parallel; let in-flight work drain for 30 seconds;  ' -ForegroundColor Yellow
Write-Host '  then summarize what you find.                                         ' -ForegroundColor Yellow
Pause-If-Interactive

Write-Step -Title "Step 3 of 5: watch the workflow card render" -Body @"
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
"@
Pause-If-Interactive

Write-Step -Title "Step 4 of 5: terminal state lands automatically" -Body @"
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
"@
Pause-If-Interactive

Write-Step -Title "Step 5 of 5 (optional): demo cooperative cancel" -Body @"
If you have time, run the demo a second time and during the 30-second
wait, send a follow-up message:

  actually cancel that

The agent should call cancel_workflow. The orchestration unwinds at the
next wave boundary, the live card flips to 'Canceled', and partial
results gathered before the cancel are still visible. Contrast this with
terminate_workflow, which would stop abruptly and not push back a
completion envelope.
"@

Write-Host ""
Write-Host "Demo dry-run complete." -ForegroundColor Green
Write-Note "If anything was wrong, fix it now and re-run this script before the live demo."
Write-Note "To clean up stale workflows between rehearsals, restart func.exe; the per-session"
Write-Note "owner key changes when the chat UI generates a new session, so old runs are hidden."
