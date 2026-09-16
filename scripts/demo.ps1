#Requires -Version 7
<#
.SYNOPSIS
  End-to-end demonstration of the P0 batch on a fresh project (~2 minutes with Blender 5.2).
.DESCRIPTION
  1. `fluidblend init` (film profile, project `demo-studio`)
  2. copy of the skill example requests into <Path>\requests\
  3. scene.build -> animation.retime -> shot.preview -> game.export -> shot.validate
  No installation, no network access (Blender is launched with --offline-mode).
.PARAMETER Path
  Folder of the demonstration project (created when missing). Spaces and accents are accepted.
.EXAMPLE
  .\scripts\demo.ps1 -Path "D:\Projects\Demo fluidblend"
#>
param(
    [Parameter(Mandatory = $true)][string]$Path,
    [switch]$SkipExport
)

$ErrorActionPreference = 'Stop'
$kit = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONIOENCODING = 'utf-8'

function Invoke-Fluidblend {
    param([string[]]$Arguments, [int[]]$AllowedExit = @(0))
    & uv run --project $kit fluidblend @Arguments
    if ($AllowedExit -notcontains $LASTEXITCODE) { throw "fluidblend $($Arguments[0]) returned $LASTEXITCODE" }
}

Write-Host "== 1/6 init =="
Invoke-Fluidblend @('init', '--path', $Path, '--profile', 'film', '--project-id', 'demo-studio', '--name', 'Demo fluidblend')
$Path = (Resolve-Path $Path).Path

Write-Host "== 2/6 doctor =="
Invoke-Fluidblend @('doctor', '--project', $Path)

Write-Host "== 3/6 example requests =="
$requests = Join-Path $Path 'requests'
New-Item -ItemType Directory -Force $requests | Out-Null
Get-ChildItem (Join-Path $kit 'skills\fluidblend\assets') -Filter 'request-*.json' | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $requests $_.Name) -Force
    Write-Host "  $($_.Name)"
}

$steps = @(
    @{ label = 'scene.build (two characters, one lantern, 240 frames)'; file = 'request-scene-build.json' },
    @{ label = 'animation.retime (hero walk x 1.2 on a variant)'; file = 'request-animation-retime.json' },
    @{ label = 'shot.preview (Workbench PNG -> MP4 + ffprobe evidence)'; file = 'request-shot-preview.json' }
)
if (-not $SkipExport) { $steps += @{ label = 'game.export (GLB + re-import, Khronos validation when available)'; file = 'request-game-export.json' } }

$total = 3 + $steps.Count + 1
$i = 4
foreach ($step in $steps) {
    Write-Host "== $i/$total $($step.label) =="
    Invoke-Fluidblend @('run', '--project', $Path, '--operation', "requests\$($step.file)")
    $i++
}

Write-Host "== $total/$total technical validation =="
Invoke-Fluidblend @('validate', '--project', $Path, '--target', 'shot010') -AllowedExit @(0, 1)

Write-Host ""
Write-Host "Project: $Path"
Write-Host "  versions : shots\shot010\work\v001, v002"
Write-Host "  preview  : renders\shot010\<operation_id>\preview.mp4 (+ ffprobe.json)"
Write-Host "  export   : exports\shot010\<operation_id>\*.glb"
Write-Host "  journal  : state\journal.jsonl ; resume : uv run --project `"$kit`" fluidblend resume --project `"$Path`""
