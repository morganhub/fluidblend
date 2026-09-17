"""Game targets (Godot here, the browser in `game_web`): a real headless import, then the prototype really launched (§14).

Generating files proves nothing: `game.import_test` checks what the engine wrote, not its exit code
alone, and `game.smoke_test` plays the template's scene through the same input path a player uses.
Without Godot the game stays `not_tested` (`MISSING_DEPENDENCY`), never "probably fine".
"""

import json
import os
import platform
import shutil
import subprocess
import time

from fluidblend.adapters.tool_paths import find_godot
from fluidblend.contracts.common import ErrorCode
from fluidblend.core.atomic import read_json
from fluidblend.core.dependencies import verify_executable
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import assert_not_protected, relpath_posix, resolve_inside
from fluidblend.core.project import kit_root
from fluidblend.hostops import game_web
from fluidblend.hostops.context import HostOpError

TEMPLATE = "templates/game-godot"
CHARACTER = "assets/character.glb"


def godot_for(ctx):
    tool = find_godot(ctx.project.local.godot_executable)
    if not tool:
        raise HostOpError(
            ErrorCode.MISSING_DEPENDENCY,
            "Godot not found: the game target stays not_tested",
            recovery="install Godot 4.7 (see `fluidblend doctor`), or set godot_executable in config/local.json",
        )
    try:
        verify_executable(ctx.project, "game.godot", tool)
    except (OSError, ValueError) as exc:
        raise HostOpError(ErrorCode.MISSING_DEPENDENCY, str(exc)) from exc
    return tool


def run_godot(ctx, godot, arguments, what):
    remaining = ctx.project.manifest.budgets.max_task_minutes * 60 - (
        time.monotonic() - ctx.started_monotonic
    )
    if remaining <= 0:
        raise HostOpError(ErrorCode.BUDGET_EXCEEDED, "game task time budget exhausted")
    try:
        return subprocess.run(
            [godot, "--headless", *arguments],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=remaining,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"Godot {what} did not complete: {exc}") from exc


def admitted(ctx, value, *, directory):
    path = resolve_inside(ctx.project.root, value, allow_missing=False)
    assert_not_protected(relpath_posix(ctx.project.root, path), ctx.project.permissions.protected_paths)
    if directory != path.is_dir():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED, f"{value} is not a {'folder' if directory else 'file'}"
        )
    return path


def import_project(ctx, godot, game):
    """Run the importer and return what it really produced for the character."""
    done = run_godot(ctx, godot, ["--path", str(game), "--import"], "import")
    marker = game / (CHARACTER + ".import")
    text = marker.read_text(encoding="utf-8") if marker.is_file() else ""
    imported = sorted((game / ".godot" / "imported").glob("character.glb-*.scn"))
    problems = []
    if done.returncode:
        problems.append(f"importer exit code {done.returncode}")
    if 'importer="scene"' not in text:
        problems.append("character.glb.import is missing or is not a scene import")
    if not imported:
        problems.append("no imported scene under .godot/imported")
    if problems:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "Godot did not import the character: " + "; ".join(problems),
            details={"stderr": done.stderr[-1500:], "stdout": done.stdout[-500:]},
        )
    return {
        "import_file": CHARACTER + ".import",
        "import_file_sha256": sha256_file(marker),
        "imported_scene_bytes": imported[0].stat().st_size,
        "exit_code": done.returncode,
    }


def engine_version(ctx, godot):
    done = run_godot(ctx, godot, ["--version"], "version probe")
    return (
        (done.stdout or done.stderr).strip().splitlines()[-1] if (done.stdout or done.stderr).strip() else ""
    )


def import_test(ctx):
    glb = admitted(ctx, ctx.params.export_path, directory=False)
    if glb.suffix.lower() != ".glb":
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "export_path must be a published .glb")
    if ctx.params.template == "web":
        return game_web.import_test(ctx, glb)
    godot = godot_for(ctx)
    game = ctx.out_dir / "game"
    shutil.copytree(
        kit_root() / TEMPLATE, game, ignore=shutil.ignore_patterns(".godot", "*.import", ".gitkeep")
    )
    shutil.copy2(glb, game / CHARACTER)
    produced = import_project(ctx, godot, game)
    # The engine's cache is machine-local and rebuilt by every run: it is evidence, not a deliverable.
    shutil.rmtree(game / ".godot", ignore_errors=True)
    for path in sorted(p for p in game.rglob("*") if p.is_file()):
        ctx.add_file("game", path)
    ctx.write_report(
        "game-import.json",
        {
            "template": TEMPLATE,
            "engine": engine_version(ctx, godot),
            "export_path": ctx.params.export_path,
            "export_sha256": sha256_file(glb),
            "game_dir": "game",
            **produced,
            "limits": ["import only: nothing was played; run game.smoke_test on the published game folder"],
        },
    )
    ctx.metrics.update({"imported": True, "imported_scene_bytes": produced["imported_scene_bytes"]})
    ctx.next_safe_actions.append("game.smoke_test with game_dir = the published game folder")


def smoke_test(ctx):
    source = admitted(ctx, ctx.params.game_dir, directory=True)
    # The published folder says which engine it was made for.
    if game_web.is_web_game(source) and (source / CHARACTER).is_file():
        return game_web.smoke_test(ctx, source)
    if not (source / "project.godot").is_file() or not (source / CHARACTER).is_file():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED, "game_dir is not a folder published by game.import_test"
        )
    godot = godot_for(ctx)
    run = ctx.task_dir / "run"
    shutil.copytree(source, run, ignore=shutil.ignore_patterns(".godot"))
    import_project(ctx, godot, run)
    report_path = ctx.out_dir / "godot-smoke.json"
    done = run_godot(
        ctx,
        godot,
        ["--path", str(run), "-s", "res://test/smoke.gd", "--", "--report", str(report_path)],
        "smoke test",
    )
    if not report_path.is_file():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "the prototype wrote no report: the run proves nothing",
            details={"exit_code": done.returncode, "stderr": done.stderr[-1500:]},
        )
    report = read_json(report_path)
    ctx.add_file("report", report_path)
    failed = [c["name"] for c in report.get("checks", []) if not c.get("passed")]
    passed = (
        done.returncode == 0
        and report.get("passed") is True
        and report.get("headless") is True
        and not failed
    )
    ctx.write_report(
        "game-smoke.json",
        {
            "game_dir": ctx.params.game_dir,
            "engine": report.get("engine"),
            "exit_code": done.returncode,
            "passed": passed,
            "checks": report.get("checks", []),
            "failed_checks": failed,
            "wall_time_ms": report.get("wall_time_ms"),
            "machine": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "cpus": os.cpu_count(),
            },
            "limits": [
                "headless run on this machine: no rendering, no frame-rate or GPU figure is claimed",
                "template gameplay only: two states, one wall, one pickup; not the user's game",
            ],
        },
    )
    ctx.metrics.update({"passed": passed, "checks": len(report.get("checks", [])), "failed_checks": failed})
    shutil.rmtree(run, ignore_errors=True)
    if not passed:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "the prototype ran and failed its smoke test",
            details={
                "failed_checks": failed,
                "exit_code": done.returncode,
                "report": json.dumps(report)[:1500],
            },
        )
