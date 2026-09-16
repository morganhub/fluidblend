#Requires -Version 7
<#
.SYNOPSIS
  Local preparation of the kit: diagnostic -> diff -> proposals. Installs nothing without -Install.
.DESCRIPTION
  1. `uv sync` (kit-local venv, no global installation)
  2. `fluidblend doctor` (real probes, capabilities.json with -Project)
  3. `fluidblend schema check` and the unit tests
  4. Lists the missing external dependencies with the suggested install command.
     With -Install, offers each installation one by one (interactive confirmation).
.EXAMPLE
  .\scripts\bootstrap.ps1
  .\scripts\bootstrap.ps1 -Project "D:\Projects\Demo Studio" -Install
#>
param(
    [string]$Project,
    [switch]$Install,
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$kit = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $kit

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv not found; install astral-sh.uv (winget), then run again" }
Write-Host "== uv sync (Python 3.13, local venv) =="
& uv sync --python 3.13
if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

Write-Host "== diagnostic =="
$doctorArgs = @('run', 'fluidblend', 'doctor', '--json', '--write-lock', (Join-Path $kit 'dependencies.lock.json'))
if ($Project) { $doctorArgs += @('--project', $Project) }
$report = & uv @doctorArgs | ConvertFrom-Json
foreach ($cap in $report.capabilities) {
    $mark = if ($cap.status -eq 'available') { '+' } elseif ($cap.status -eq 'unverified') { '?' } else { '-' }
    Write-Host ("  [{0}] {1,-24} {2}" -f $mark, $cap.capability_id, $cap.status)
}

$proposals = @{
    'gltf.khronos_validator' = 'Download gltf_validator-2.0.0-dev.3.10-win64.zip (Apache-2.0) from https://github.com/KhronosGroup/glTF-Validator/releases and set gltf_validator_executable in config/local.json'
    'game.godot'             = 'winget install --id GodotEngine.GodotEngine --version 4.7.2 --exact'
    'audio.rhubarb'          = 'Download Rhubarb-Lip-Sync-1.14.0-Windows.zip (MIT) from https://github.com/DanielSWolf/rhubarb-lip-sync/releases and set rhubarb_executable'
    'video.ffmpeg'           = 'winget install Gyan.FFmpeg'
    'blender.mcp_addon'      = 'uvx mcp-for-blender install-addon   (then enable the add-on in the Blender 5.2 GUI)'
    'blender.batch'          = 'Install Blender 5.2.x LTS (winget install BlenderFoundation.Blender) or set blender_executable'
}
$missing = $report.capabilities | Where-Object { $_.status -in @('not_installed', 'not_configured', 'incompatible') -and $proposals.ContainsKey($_.capability_id) }
if ($missing) {
    Write-Host ""
    Write-Host "== missing dependencies (proposals, nothing runs without confirmation) =="
    foreach ($cap in $missing) {
        Write-Host ("  {0}: {1}" -f $cap.capability_id, $proposals[$cap.capability_id])
        if ($Install -and $proposals[$cap.capability_id] -like 'winget *') {
            $answer = Read-Host "  Run it now? (y/N)"
            if ($answer -match '^[yY]') { Invoke-Expression $proposals[$cap.capability_id] }
        }
    }
}

Write-Host ""
Write-Host "== schemas =="
& uv run fluidblend schema check --out schemas
if ($LASTEXITCODE -ne 0) { Write-Warning "stale schemas: uv run fluidblend schema export --out schemas" }

if (-not $SkipTests) {
    Write-Host "== unit tests (without Blender) =="
    & uv run pytest tests/unit -q
}
Write-Host ""
Write-Host "Done. Full acceptance: uv run pytest tests -q -m 'not slow' ; report: uv run pytest tests --acceptance-report docs/acceptance-reports/latest-p0"
