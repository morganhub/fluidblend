"""environment.doctor: real probes -> `capabilities.json` (§3.3). Read-only, apart from the report it writes."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fluidblend import __version__
from fluidblend.adapters import blender_discovery, client_config
from fluidblend.adapters import gltf_validator as gltfv
from fluidblend.contracts.capabilities import CapabilitiesReport, Capability, CapabilityStatus
from fluidblend.contracts.project import LocalConfig
from fluidblend.core.atomic import atomic_write_json
from fluidblend.core.hashing import now_iso, sha256_file


def _exe_version(executable: str, args: list[str]) -> str | None:
    try:
        completed = subprocess.run(
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr).strip().splitlines()
    return text[0].strip() if text else None


def _tool_capability(
    capability_id: str,
    name: str,
    configured: str | None,
    version_args: list[str],
    *,
    fallback: str | None,
    install_hint: str,
) -> Capability:
    from fluidblend.adapters.tool_paths import find_executable, find_godot

    executable = find_godot(configured) if name == "godot" else find_executable(name, configured)
    now = now_iso()
    if not executable:
        return Capability(
            capability_id=capability_id,
            provider=name,
            status=CapabilityStatus.not_installed,
            verified_at=now,
            error=f"{name} not found in PATH nor in config/local.json",
            fallback=fallback,
            restrictions=[install_hint],
        )
    version = _exe_version(executable, version_args)
    return Capability(
        capability_id=capability_id,
        provider=name,
        version=version,
        transport="subprocess",
        executable=executable,
        status=CapabilityStatus.available if version else CapabilityStatus.unverified,
        verified_at=now,
        evidence={
            "version_line": version,
            "sha256": sha256_file(Path(executable)) if Path(executable).is_file() else None,
        },
        fallback=fallback,
    )


def _blender_capability(
    local: LocalConfig | None, *, probe: bool
) -> tuple[Capability, dict[str, Any] | None]:
    now = now_iso()
    candidates = blender_discovery.discover_blender(local)
    if not candidates:
        return Capability(
            capability_id="blender.batch",
            provider="Blender",
            status=CapabilityStatus.not_installed,
            verified_at=now,
            error="no blender.exe found (registry, Program Files, PATH, config)",
            restrictions=["install Blender 5.2.x LTS"],
        ), None
    chosen = None
    probe_info: dict[str, Any] | None = None
    notes: list[str] = []
    for cand in candidates:
        if not probe:
            if (cand.version_hint or "").startswith(blender_discovery.LOCKED_BLENDER_SERIES):
                chosen = cand
                break
            continue
        result = blender_discovery.probe_blender(
            cand.path, timeout=(local.blender_startup_timeout_s if local else 90.0)
        )
        if not result.ok:
            notes.append(f"{cand.path}: {result.error}")
            continue
        if blender_discovery.is_locked_series(result.info):
            chosen, probe_info = cand, {**result.info, "probe_seconds": round(result.elapsed_s, 2)}
            break
        notes.append(
            f"{cand.path}: {result.info.get('version_string')} (outside series {blender_discovery.LOCKED_BLENDER_SERIES})"
        )
    if chosen is None:
        return Capability(
            capability_id="blender.batch",
            provider="Blender",
            status=CapabilityStatus.incompatible,
            verified_at=now,
            error="no Blender from the locked series " + blender_discovery.LOCKED_BLENDER_SERIES,
            evidence={"candidates": [c.__dict__ for c in candidates], "notes": notes},
            restrictions=["the kit is validated on Blender 5.2.x only"],
        ), None
    status = CapabilityStatus.available if probe_info else CapabilityStatus.unverified
    restrictions = [
        "batch mode: `bpy.app.timers` inactive, synchronous execution",
        "--disable-autoexec by default: drivers/scripts of third-party .blend files disabled",
    ]
    if probe_info and probe_info.get("legacy_fcurves"):
        restrictions.append("legacy Action.fcurves API present: not used by the runtime")
    return Capability(
        capability_id="blender.batch",
        provider="Blender",
        version=(probe_info or {}).get("version_string") or chosen.version_hint,
        transport="subprocess --background",
        executable=chosen.path,
        tools=[
            "scene.build",
            "scene.inspect",
            "scene.audit",
            "animation.retime",
            "shot.preview",
            "game.export",
        ],
        status=status,
        verified_at=now,
        evidence={
            "source": chosen.source,
            "probe": probe_info,
            "sha256": sha256_file(Path(chosen.path)),
            "other_candidates": notes,
        },
        restrictions=restrictions,
    ), probe_info


def _mcp_capabilities(
    project_root: Path | None, local: LocalConfig | None, *, live: bool
) -> list[Capability]:
    now = now_iso()
    caps: list[Capability] = []
    servers = client_config.configured_servers(project_root=project_root or Path.cwd())
    blender_servers = [
        s
        for s in servers
        if any("blender" in str(a).lower() for a in [s.get("name"), s.get("command"), *s.get("args", [])])
    ]
    addon = client_config.blender_mcp_addon_installed()
    caps.append(
        Capability(
            capability_id="blender.mcp_addon",
            provider="mcp-for-blender (add-on)",
            status=CapabilityStatus.available if addon["installed"] else CapabilityStatus.not_installed,
            verified_at=now,
            evidence=addon,
            restrictions=[
                "unauthenticated localhost TCP socket: never expose the port",
                "the add-on refuses to start under blender --background",
            ],
            error=None
            if addon["installed"]
            else "MCP add-on missing from the Blender profile; install it with `uvx mcp-for-blender install-addon` (approval required)",
            fallback="batch mode",
        )
    )
    if not blender_servers:
        caps.append(
            Capability(
                capability_id="blender.mcp_live",
                provider="mcp-for-blender",
                status=CapabilityStatus.not_configured,
                verified_at=now,
                error="no Blender MCP server declared in .mcp.json / ~/.claude.json / config.toml / mcp.json",
                fallback="batch mode",
                restrictions=["generate a configuration: `fluidblend client-config --client claude`"],
            )
        )
        return caps
    server = blender_servers[0]
    cap = Capability(
        capability_id="blender.mcp_live",
        provider="mcp-for-blender",
        transport="stdio -> TCP socket",
        executable=str(server.get("command")),
        status=CapabilityStatus.unverified,
        verified_at=now,
        evidence={"configured": server, "all_blender_servers": blender_servers},
        restrictions=["a configuration file being present does not mean the connection works"],
        fallback="batch mode",
    )
    if live:
        from fluidblend.adapters import mcp_client

        mcp = local.mcp if local else None
        report = mcp_client.probe_server(
            str(server.get("command")),
            [str(a) for a in server.get("args", [])],
            None,
            startup_timeout_s=mcp.startup_timeout_s if mcp else 20.0,
            call_timeout_s=mcp.call_timeout_s if mcp else 60.0,
        )
        cap.tools = report.get("tools", [])
        cap.evidence["live_probe"] = {k: v for k, v in report.items() if k != "tools"}
        if report.get("errors"):
            cap.status = CapabilityStatus.blocked
            cap.error = "; ".join(report["errors"])
        elif report.get("scene_info") and not report["scene_info"].get("is_error"):
            cap.status = CapabilityStatus.available
        else:
            cap.status = CapabilityStatus.unverified
            cap.error = "tools listed but get_scene_info missing or failing (Blender GUI open with the add-on started?)"
    caps.append(cap)
    return caps


def capabilities_to_lock(report: CapabilitiesReport) -> dict[str, Any]:
    """`dependencies.lock.json`: observed versions, hashes and provenance - without machine paths.

    Executable paths and workstation details stay in `state/diagnostics/capabilities.json` (not
    versioned); the lock file itself is publishable.
    """
    from fluidblend.contracts.project import DependencyEntry, DependencyLock

    lock = DependencyLock()
    for cap in report.capabilities:
        lock.dependencies[cap.capability_id] = DependencyEntry(
            name=cap.provider,
            version=cap.version,
            sha256=(cap.evidence or {}).get("sha256"),
            source=(cap.evidence or {}).get("source"),
            verified_at=cap.verified_at,
            status=cap.status.value,
        )
    lock.extra = {
        "generated_at": report.generated_at,
        "fluidblend": __version__,
        "blender_locked_series": blender_discovery.LOCKED_BLENDER_SERIES,
        "platform": report.host.get("platform"),
        "python": report.host.get("python"),
    }
    return lock.model_dump(mode="json")


def run_doctor(
    project_root: Path | None, local: LocalConfig | None, *, probe_blender: bool = True, live: bool = False
) -> CapabilitiesReport:
    caps: list[Capability] = []
    blender_cap, _info = _blender_capability(local, probe=probe_blender)
    caps.append(blender_cap)
    caps.append(
        _tool_capability(
            "video.ffmpeg",
            "ffmpeg",
            local.ffmpeg_executable if local else None,
            ["-version"],
            fallback="PNG frames without video",
            install_hint="winget install Gyan.FFmpeg",
        )
    )
    caps.append(
        _tool_capability(
            "video.ffprobe",
            "ffprobe",
            local.ffprobe_executable if local else None,
            ["-version"],
            fallback=None,
            install_hint="winget install Gyan.FFmpeg",
        )
    )
    validator = gltfv.find_validator(local.gltf_validator_executable if local else None)
    caps.append(
        Capability(
            capability_id="gltf.khronos_validator",
            provider="KhronosGroup/glTF-Validator",
            executable=validator,
            status=CapabilityStatus.available if validator else CapabilityStatus.not_installed,
            verified_at=now_iso(),
            evidence={"sha256": sha256_file(Path(validator)) if validator else None},
            error=None if validator else "gltf_validator not found: export acceptance marked not_run",
            restrictions=["2.0.0-dev.3.10 win64 binary recommended (Apache-2.0)"],
            fallback="Blender re-import alone (not enough to declare the acceptance validated)",
        )
    )
    caps.append(
        _tool_capability(
            "game.godot",
            "godot",
            local.godot_executable if local else None,
            ["--version"],
            fallback="GLB delivered as an export, game not_tested",
            install_hint="winget install --id GodotEngine.GodotEngine --version 4.7.2 --exact",
        )
    )
    caps.append(
        _tool_capability(
            "audio.rhubarb",
            "rhubarb",
            local.rhubarb_executable if local else None,
            ["--version"],
            fallback="lip-sync unavailable",
            install_hint="Rhubarb-Lip-Sync-1.14.0-Windows.zip (MIT)",
        )
    )
    uv = shutil.which("uv")
    caps.append(
        Capability(
            capability_id="python.uv",
            provider="astral-sh/uv",
            executable=uv,
            version=_exe_version(uv, ["--version"]) if uv else None,
            status=CapabilityStatus.available if uv else CapabilityStatus.not_installed,
            verified_at=now_iso(),
            restrictions=(
                ["binary shipped by Langflow Desktop, not a standalone installation"]
                if uv and "langflow" in uv.lower()
                else []
            ),
        )
    )
    from fluidblend.core import runtime_install

    try:
        rt = runtime_install.runtime_status()
        if rt["installed"] and rt["up_to_date"]:
            rt_status = CapabilityStatus.available
        elif rt["installed"]:
            rt_status = CapabilityStatus.incompatible
        else:
            rt_status = CapabilityStatus.not_installed
        caps.append(
            Capability(
                capability_id="blender.runtime_addon",
                provider="fluidblend runtime (Blender add-on)",
                version=(rt.get("manifest") or {}).get("version"),
                executable=rt["path"],
                tools=["fluidblend.identity", "fluidblend.run_request", "fluidblend.open_file"],
                status=rt_status,
                verified_at=now_iso(),
                evidence={
                    "kit_hash": rt["kit_hash"],
                    "installed_hash": rt["installed_hash"],
                    "up_to_date": rt["up_to_date"],
                },
                error=None
                if rt_status == CapabilityStatus.available
                else "run `fluidblend runtime install --enable` (approved install into the Blender user add-ons directory)",
                restrictions=["required for live mode only; batch mode uses the kit copy"],
                fallback="batch mode",
            )
        )
    except RuntimeError as exc:
        caps.append(
            Capability(
                capability_id="blender.runtime_addon",
                provider="fluidblend runtime (Blender add-on)",
                status=CapabilityStatus.unverified,
                verified_at=now_iso(),
                error=str(exc),
            )
        )
    caps.extend(_mcp_capabilities(project_root, local, live=live))
    report = CapabilitiesReport(
        generated_at=now_iso(),
        host={
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "fluidblend": __version__,
            "cwd": os.getcwd(),
            "project_root": str(project_root) if project_root else None,
        },
        capabilities=caps,
    )
    if project_root is not None:
        atomic_write_json(
            project_root / "state" / "diagnostics" / "capabilities.json", report.model_dump(mode="json")
        )
    return report
