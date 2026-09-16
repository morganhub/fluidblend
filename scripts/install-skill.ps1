#Requires -Version 7
<#
.SYNOPSIS
  Grafts the `fluidblend` skill into a project (Claude Code and/or Codex), on explicit request.
.DESCRIPTION
  Copies skills/fluidblend into <Target>/.claude/skills/fluidblend and/or <Target>/.agents/skills/fluidblend,
  writes kit-path.txt (absolute path of the kit) inside the copy and, with -WithMcp, merges a
  `blender` entry (mcp-for-blender, safe mode, telemetry off) into <Target>/.mcp.json without overwriting the other servers.
  Never touches ~/.claude nor ~/.codex: project-local installation only.
.PARAMETER Target
  Root of the target project (existing folder).
.PARAMETER Client
  claude | codex | both (default: both).
.PARAMETER WithMcp
  Generates/merges .mcp.json (Claude Code) for the live mode.
.PARAMETER Force
  Replaces an already present but different copy of the skill.
.EXAMPLE
  .\scripts\install-skill.ps1 -Target "D:\Projects\My Film" -Client both -WithMcp
#>
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [ValidateSet('claude', 'codex', 'both')][string]$Client = 'both',
    [switch]$WithMcp,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$kit = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$source = Join-Path $kit 'skills\fluidblend'
if (-not (Test-Path (Join-Path $source 'SKILL.md'))) { throw "skill source not found: $source" }
if (-not (Test-Path $Target -PathType Container)) { throw "target folder not found: $Target" }
$Target = (Resolve-Path $Target).Path

$destinations = @()
if ($Client -in @('claude', 'both')) { $destinations += (Join-Path $Target '.claude\skills\fluidblend') }
if ($Client -in @('codex', 'both')) { $destinations += (Join-Path $Target '.agents\skills\fluidblend') }

function Get-TreeHash([string]$root) {
    $files = Get-ChildItem $root -Recurse -File | Where-Object { $_.Name -ne 'kit-path.txt' } | Sort-Object FullName
    $sb = [System.Text.StringBuilder]::new()
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($root.Length)
        [void]$sb.Append($rel).Append('|').Append((Get-FileHash $f.FullName -Algorithm SHA256).Hash).Append("`n")
    }
    return $sb.ToString()
}

foreach ($dest in $destinations) {
    if (Test-Path $dest) {
        if ((Get-TreeHash $source) -eq (Get-TreeHash $dest)) {
            Write-Host "identical, nothing to do: $dest"
        } elseif ($Force) {
            Remove-Item $dest -Recurse -Force
            Copy-Item $source $dest -Recurse
            Write-Host "replaced (-Force): $dest"
        } else {
            Write-Warning "existing copy differs, kept: $dest (run again with -Force to replace)"
            continue
        }
    } else {
        New-Item -ItemType Directory -Force (Split-Path $dest -Parent) | Out-Null
        Copy-Item $source $dest -Recurse
        Write-Host "installed: $dest"
    }
    Set-Content -Path (Join-Path $dest 'kit-path.txt') -Value $kit -Encoding utf8 -NoNewline
}

if ($WithMcp) {
    $mcpPath = Join-Path $Target '.mcp.json'
    & uv run --project $kit fluidblend client-config --client claude --write $mcpPath
    if ($LASTEXITCODE -ne 0) { throw "client-config failed ($LASTEXITCODE)" }
    Write-Host "MCP: 'blender' entry merged into $mcpPath (the MCP for Blender add-on must be installed separately, after approval)"
}

Write-Host ""
Write-Host "Next steps:"
Write-Host "  uv run --project `"$kit`" fluidblend doctor --project `"$Target`""
Write-Host "  uv run --project `"$kit`" fluidblend init --path `"$Target`" --profile film --dry-run"
