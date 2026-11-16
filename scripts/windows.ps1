# JobPilot on Windows: the same steps as the Makefile, for PowerShell (no make or bash needed).
#
#   powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 install          # packages, browser, web app, database
#   powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 serve            # http://127.0.0.1:8000 (Ctrl+C stops)
#   powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 startup-install  # start hidden at every log-in
#   powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 startup-remove
#   powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 update           # after git pull
#   powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 doctor           # what is still missing

param([Parameter(Position = 0)][string]$Command = "help")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "JobPilot"
Set-Location $Root

function Need($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { throw "$name is not installed. $hint" }
}

function Run($exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$exe $($arguments -join ' ') failed (exit $LASTEXITCODE)" }
}

function Build-Web {
    Push-Location (Join-Path $Root "web")
    try { Run "npm" @("install"); Run "npm" @("run", "build") } finally { Pop-Location }
}

switch ($Command) {
    "install" {
        Need "uv" "Install it: powershell -ExecutionPolicy ByPass -c `"irm https://astral.sh/uv/install.ps1 | iex`""
        Need "node" "Install Node.js 20 or newer from https://nodejs.org (or: winget install OpenJS.NodeJS.LTS)"
        Run "uv" @("sync")
        Run "uv" @("run", "playwright", "install", "chromium")
        Build-Web
        Run "uv" @("run", "jobagent", "init")
        Write-Host "`nInstalled. Next: scripts\windows.ps1 serve, then open http://127.0.0.1:8000"
    }
    "build" { Build-Web }
    "serve" { Run "uv" @("run", "jobagent", "serve") }
    "update" {
        Run "uv" @("sync")
        Run "uv" @("run", "playwright", "install", "chromium")
        Build-Web
        Write-Host "Updated. Restart JobPilot (or log out and in, if it starts at log-in)."
    }
    "doctor" { Run "uv" @("run", "jobagent", "doctor") }
    "startup-install" {
        $uv = (Get-Command uv).Source
        New-Item -ItemType Directory -Force (Join-Path $Root "data") | Out-Null
        $log = Join-Path $Root "data\server.log"
        # A hidden PowerShell runs the server in this folder, so no console window stays open.
        $inner = "Set-Location -LiteralPath '$Root'; & '$uv' run jobagent serve *>> '$log'"
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"$inner`"" -WorkingDirectory $Root
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
        # Runs as you, only while you're logged in, so sign-in windows can appear on your screen.
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
            -Principal $principal -Description "JobPilot server on http://127.0.0.1:8000" -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        Write-Host "JobPilot now starts when you log in (and is starting now). Logs: $log"
    }
    "startup-remove" {
        if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
            Write-Host "Removed: JobPilot no longer starts at log-in."
        } else { Write-Host "JobPilot was not set to start at log-in." }
    }
    default {
        Write-Host "Usage: powershell -ExecutionPolicy Bypass -File scripts\windows.ps1 <command>"
        Write-Host "Commands: install, serve, build, update, doctor, startup-install, startup-remove"
    }
}
