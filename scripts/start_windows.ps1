# Start the nabla API and a public Cloudflare tunnel on Windows, and keep the laptop awake.
#
#   powershell -ExecutionPolicy Bypass -File scripts\start_windows.ps1
#
# Reads SV_DATA_ROOT / SV_DATA_TOKEN from the environment, or from a local .env file
# (gitignored; one KEY=value per line). The token is never written into the repo.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$py = "C:\Users\ezeki\AppData\Local\Programs\Python\Python313\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

if (Test-Path "$repo\.env") {
    Get-Content "$repo\.env" | Where-Object { $_ -match "^\s*[^#].*=" } | ForEach-Object {
        $k, $v = $_ -split "=", 2
        [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
    }
}
if (-not $env:SV_DATA_ROOT) { $env:SV_DATA_ROOT = "https://pop-os.tail01ad.ts.net" }
if (-not $env:SV_DATA_TOKEN) { $env:SV_DATA_TOKEN = Read-Host "SV_DATA_TOKEN" }

# never sleep on AC power while this runs (restore later with: powercfg /change standby-timeout-ac 30)
powercfg /change standby-timeout-ac 0
powercfg /change monitor-timeout-ac 0

$envLine = "`$env:SV_DATA_ROOT='$($env:SV_DATA_ROOT)'; `$env:SV_DATA_TOKEN='$($env:SV_DATA_TOKEN)'"
Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$repo'; $envLine; & '$py' -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
Start-Sleep -Seconds 5
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cloudflared tunnel --url http://localhost:8000"

Write-Host ""
Write-Host "Two windows opened: the API (port 8000) and the tunnel."
Write-Host "Copy the https://....trycloudflare.com URL from the tunnel window, then check:"
Write-Host "  http://localhost:8000/health   (warm should read 'ok through ...' after a minute or two)"
Write-Host "Keep both windows open and the laptop plugged in during judging."
