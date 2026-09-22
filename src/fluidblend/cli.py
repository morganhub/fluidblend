"""`fluidblend` CLI: single entry point of the engine. Human output or `--json`, documented exit codes."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

from fluidblend import __version__
from fluidblend.contracts.operations import OPERATIONS, RequestValidationError, validate_request
from fluidblend.core import exit_codes
from fluidblend.core.atomic import read_json
from fluidblend.core.project import ProjectError, inspect_project, load_project, scaffold_project
from fluidblend.core.state import StateStore

EXIT_HELP = "\n".join(f"  {code}: {text}" for code, text in exit_codes.DESCRIPTIONS.items())


def _emit(data: Any, *, as_json: bool, human: str | None = None) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        print(human if human is not None else json.dumps(data, indent=2, ensure_ascii=False, default=str))


def _project(args: argparse.Namespace):
    return load_project(Path(args.project))


def _load_request(path_text: str, project_root: Path | None) -> dict[str, Any]:
    path = Path(path_text)
    if not path.is_absolute() and project_root is not None:
        path = project_root / path
    return read_json(path)


# --- Commands -------------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    from fluidblend.doctor import run_doctor

    root = None
    local = None
    project = None
    if args.project:
        try:
            project = _project(args)
            root, local = project.root, project.local
        except ProjectError as exc:
            _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
            return exit_codes.INVALID
    report = run_doctor(root, local, probe_blender=not args.no_probe, live=args.live)
    data = report.model_dump(mode="json")
    from fluidblend.core.atomic import atomic_write_json
    from fluidblend.doctor import capabilities_to_lock

    lock_targets = []
    if project is not None:
        from fluidblend.core.dependencies import compare_lock
        from fluidblend.core.paths import resolve_inside

        try:
            data["dependency_lock_comparison"] = compare_lock(
                resolve_inside(project.root, project.manifest.dependency_lock), report
            )
        except (OSError, ValueError) as exc:
            _emit({"error": f"invalid dependency lock: {exc}"}, as_json=args.json)
            return exit_codes.INVALID
    if args.write_lock:
        lock_targets.append(Path(args.write_lock))
    for target in lock_targets:
        atomic_write_json(target, capabilities_to_lock(report))
    if lock_targets:
        data["dependency_lock_written"] = [str(t) for t in lock_targets]
    lines = [f"fluidblend {__version__} - diagnostic {report.generated_at}"]
    for cap in report.capabilities:
        detail = cap.version or cap.executable or ""
        lines.append(f"  [{cap.status:>14}] {cap.capability_id:<24} {detail}")
        if cap.error:
            lines.append(f"{'':18}↳ {cap.error}")
    if root:
        lines.append(f"report: {root / 'state' / 'diagnostics' / 'capabilities.json'}")
        lines.append(
            f"dependency lock: {data['dependency_lock_comparison']['status']} (not modified by diagnostic)"
        )
    _emit(data, as_json=args.json, human="\n".join(lines))
    if data.get("dependency_lock_comparison", {}).get("status") == "mismatch":
        return exit_codes.BLOCKED
    return exit_codes.OK


def cmd_init(args: argparse.Namespace) -> int:
    project_id = args.project_id or Path(args.path).name.lower().replace(" ", "-")
    import re

    project_id = re.sub(r"[^a-z0-9._-]", "-", project_id).strip("-") or "project"
    try:
        report = scaffold_project(
            Path(args.path),
            profile=args.profile,
            project_id=project_id,
            name=args.name,
            game_engine=args.game_engine,
            dry_run=args.dry_run,
        )
    except (ProjectError, OSError) as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    human = [
        f"{'[dry-run] ' if args.dry_run else ''}project {project_id} ({args.profile}) -> {report['root']}",
        f"  directories created: {len(report['created_dirs'])}, files created: {len(report['created_files'])}, identical: {len(report['identical'])}, conflicts: {len(report['conflicts'])}",
    ]
    for conflict in report["conflicts"]:
        human.append(f"  conflict kept: {conflict['path']}")
    _emit(report, as_json=args.json, human="\n".join(human))
    return exit_codes.CONFLICT if report["conflicts"] and args.strict else exit_codes.OK


def cmd_inspect(args: argparse.Namespace) -> int:
    try:
        project = _project(args)
    except ProjectError as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    data = inspect_project(project)
    lines = [f"project {data['project']['project_id']} ({data['project']['profile']}) - {data['root']}"]
    for shot in data["shots"]:
        lines.append(
            f"  shot {shot['shot_id']}: versions {shot['work_versions'] or '-'}; state {shot['validation_state']}"
        )
    for target, rev in data["revisions"].items():
        lines.append(f"  revision {target} = {rev['revision']} ({rev['path']})")
    lines.append(
        f"  tasks: {len(data['tasks'])} (unfinished: {data['unfinished_tasks'] or 'none'}); checkpoints: {data['checkpoints']}"
    )
    _emit(data, as_json=args.json, human="\n".join(lines))
    return exit_codes.OK


def cmd_plan(args: argparse.Namespace) -> int:
    from fluidblend.core.planner import make_plan

    try:
        project = _project(args)
        payload = _load_request(args.request, project.root)
        request, params, spec = validate_request(payload)
    except (ProjectError, OSError, ValueError, RequestValidationError) as exc:
        details = getattr(exc, "details", None)
        _emit(
            {"error": str(exc), "details": details},
            as_json=args.json,
            human=f"error: {exc}\n{json.dumps(details, indent=1, ensure_ascii=False) if details else ''}",
        )
        return exit_codes.INVALID
    plan = make_plan(project, request, params, spec, save=True)
    data = plan.model_dump(mode="json")
    lines = [f"plan {plan.operation_id} - {plan.operation} ({plan.backend}, {plan.op_class}, {plan.lot})"]
    lines.append(
        f"  estimate: {plan.estimated_seconds:.0f} s, {plan.estimated_new_disk_mib:.0f} MiB; permission ok: {plan.permission_ok}"
    )
    for step in plan.steps:
        lines.append(f"  - {step}")
    for err in plan.blocking_errors:
        lines.append(f"  BLOCKING {err.code}: {err.message}")
    _emit(data, as_json=args.json, human="\n".join(lines))
    return exit_codes.BLOCKED if plan.blocking_errors else exit_codes.OK


def cmd_run(args: argparse.Namespace) -> int:
    from fluidblend.core.tasks import TaskRunner

    try:
        project = _project(args)
        payload = _load_request(args.operation, project.root)
    except (ProjectError, OSError, ValueError) as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    runner = TaskRunner(project, mode=args.mode)
    outcome = runner.run(payload, force_dry_run=args.dry_run)
    result = outcome.result.model_dump(mode="json")
    result["exit_code"] = outcome.exit_code
    result["replayed"] = outcome.replayed
    lines = [
        f"{result['operation']} [{result['operation_id']}] -> {result['status']} (exit {outcome.exit_code}{', idempotent replay' if outcome.replayed else ''})"
    ]
    if result.get("task_id"):
        lines.append(f"  task: {result['task_id']}")
    for artifact in result["artifacts"]:
        lines.append(f"  artifact {artifact['kind']:<7} {artifact['path']}")
    for warning in result["warnings"]:
        lines.append(f"  ⚠ {warning}")
    for error in result["errors"]:
        lines.append(f"  ✗ {error['code']}: {error['message']}")
        if error.get("recovery"):
            lines.append(f"    → {error['recovery']}")
    if result.get("new_revision") is not None:
        lines.append(f"  new revision: {result['new_revision']}")
    _emit(result, as_json=args.json, human="\n".join(lines))
    return outcome.exit_code


def cmd_task(args: argparse.Namespace) -> int:
    from fluidblend.core.tasks import TaskRunner

    try:
        project = _project(args)
        runner = TaskRunner(project)
        if args.task_command == "status":
            data = runner.status(args.id)
        elif args.task_command == "cancel":
            data = runner.cancel(args.id)
        elif args.task_command == "reconcile":
            data = runner.reconcile(args.id)
        else:
            data = {"tasks": [t.model_dump(mode="json") for t in StateStore(project.root).tasks()]}
    except ProjectError as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    _emit(data, as_json=args.json)
    if args.task_command in ("cancel", "reconcile") and data.get("status") == "unknown":
        return exit_codes.UNKNOWN_STATE
    return exit_codes.OK


def cmd_validate(args: argparse.Namespace) -> int:
    from fluidblend.core.hashing import new_id
    from fluidblend.core.tasks import TaskRunner

    try:
        project = _project(args)
    except ProjectError as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    payload = {
        "schema_version": "1.0",
        "operation": "shot.validate",
        "operation_id": new_id(f"validate-{args.target}"),
        "project_id": project.project_id,
        "target": {"shot_id": args.target},
        "parameters": {"require_preview": not args.no_preview},
    }
    outcome = TaskRunner(project).run(payload)
    data = outcome.result.model_dump(mode="json")
    passed = data.get("metrics", {}).get("technical_pass")
    _emit(
        data,
        as_json=args.json,
        human=f"validation {args.target}: technical_pass={passed}; failures: {data.get('metrics', {}).get('failed_checks')}",
    )
    if outcome.exit_code != exit_codes.OK:
        return outcome.exit_code
    return exit_codes.OK if passed else exit_codes.FAILED


def cmd_resume(args: argparse.Namespace) -> int:
    from fluidblend.core.atomic import atomic_write_json

    try:
        project = _project(args)
    except ProjectError as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    store = StateStore(project.root)
    state = store.rebuild(save=True)
    unfinished = store.unfinished_tasks()
    report = {
        "project_id": project.project_id,
        "events": state["event_count"],
        "corrupt_lines": state["corrupt_lines"],
        "unfinished_tasks": [t.model_dump(mode="json") for t in unfinished],
        "next_actions": [f"fluidblend task reconcile --project . --id {t.task_id}" for t in unfinished],
        "inspect": inspect_project(project),
    }
    atomic_write_json(project.root / "state" / "resume-report.json", report)
    lines = [
        f"resume {project.project_id}: {state['event_count']} events, {len(unfinished)} task(s) to reconcile"
    ]
    lines.extend(f"  → {action}" for action in report["next_actions"])
    _emit(report, as_json=args.json, human="\n".join(lines))
    return exit_codes.UNKNOWN_STATE if unfinished else exit_codes.OK


def cmd_revision(args: argparse.Namespace) -> int:
    from fluidblend.core.revisions import RevisionStore

    try:
        project = _project(args)
        store = RevisionStore(project.root)
        if args.revision_command == "accept":
            record = store.accept_external(f"shot:{args.target}")
            project.journal().append(
                "external_change_accepted",
                target=record.target,
                revision=record.revision,
                sha256=record.sha256,
            )
            _emit(
                record.model_dump(mode="json"),
                as_json=args.json,
                human=f"revision {record.target} = {record.revision} (external change accepted)",
            )
        else:
            _emit(store.load().model_dump(mode="json"), as_json=args.json)
    except (ProjectError, KeyError) as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    return exit_codes.OK


def cmd_ops(args: argparse.Namespace) -> int:
    rows = [
        {
            "operation": s.name,
            "backend": s.backend,
            "class": s.op_class,
            "lot": s.lot,
            "available": s.available,
            "description": s.description,
            **s.execution_contract(),
        }
        for s in OPERATIONS.values()
        if args.all or s.available
    ]
    lines = [
        f"  {'✓' if r['available'] else '✗'} {r['operation']:<24} {r['backend']:<7} {r['class']:<6} {r['lot']}  {r['description']}"
        for r in rows
    ]
    _emit(rows, as_json=args.json, human="\n".join(lines))
    return exit_codes.OK


def cmd_schema(args: argparse.Namespace) -> int:
    from fluidblend.contracts.schema_export import check_up_to_date, export_all

    out = Path(args.out)
    if args.schema_command == "check":
        stale = check_up_to_date(out)
        _emit(
            {"stale": stale},
            as_json=args.json,
            human=("schemas up to date" if not stale else "stale schemas: " + ", ".join(stale)),
        )
        return exit_codes.OK if not stale else exit_codes.FAILED
    written = export_all(out)
    _emit(
        {"written": [str(p) for p in written]},
        as_json=args.json,
        human=f"{len(written)} schemas written to {out}",
    )
    return exit_codes.OK


def cmd_client_config(args: argparse.Namespace) -> int:
    from fluidblend.adapters import client_config

    entry = client_config.mcp_server_entry(
        port=args.port, host=args.host, safe_mode=not args.no_safe_mode, telemetry=False
    )
    target = Path(args.write) if args.write else None
    if args.client == "codex":
        existing = target.read_text(encoding="utf-8") if target and target.exists() else ""
        text = client_config.merge_codex_toml(existing, args.name, entry)
        if target:
            target.write_text(text, encoding="utf-8")
        print(text if not target else f"written: {target}")
        return exit_codes.OK
    existing_json = read_json(target) if target and target.exists() else None
    data = (
        client_config.claude_mcp_json(existing_json, args.name, entry)
        if args.client == "claude"
        else client_config.vscode_mcp_json(existing_json, args.name, entry)
    )
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if target:
        target.write_text(text, encoding="utf-8")
        print(f"written: {target}")
    else:
        print(text)
    return exit_codes.OK


def cmd_runtime(args: argparse.Namespace) -> int:
    from fluidblend.adapters import blender_discovery
    from fluidblend.core import runtime_install

    if args.runtime_command == "status":
        data = runtime_install.runtime_status()
        state = "installed" if data["installed"] else "not installed"
        _emit(
            data,
            as_json=args.json,
            human=f"runtime add-on {state} at {data['path']}; up to date: {data['up_to_date']}",
        )
        return exit_codes.OK if data["installed"] and data["up_to_date"] else exit_codes.BLOCKED
    data = runtime_install.install_runtime(force=args.force)
    lines = [
        f"runtime add-on {data['action']} at {data['path']} (version {data['kit_version']}, hash {data['kit_hash'][:12]})"
    ]
    if args.enable:
        candidate, _probe, notes = blender_discovery.select_blender(None, probe=False)
        if candidate is None:
            data["enable"] = {"ok": False, "notes": notes}
            _emit(
                data,
                as_json=args.json,
                human="\n".join(lines + ["no Blender 5.2 found to enable the add-on"]),
            )
            return exit_codes.BLOCKED
        enabled = runtime_install.enable_runtime_addon(candidate.path)
        data["enable"] = enabled
        lines.append(f"enabled in Blender preferences: {enabled.get('ok')} ({candidate.path})")
        if not enabled.get("ok"):
            _emit(data, as_json=args.json, human="\n".join(lines))
            return exit_codes.FAILED
    _emit(data, as_json=args.json, human="\n".join(lines))
    return exit_codes.OK


def cmd_live(args: argparse.Namespace) -> int:
    from fluidblend.adapters import blender_live

    try:
        project = _project(args)
    except ProjectError as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    config = blender_live.server_config_for(project)
    try:
        ident = blender_live.identity(config)
    except blender_live.LiveError as exc:
        _emit(
            {"error": str(exc), "kind": exc.kind, "server": config.source},
            as_json=args.json,
            human=f"live session unavailable ({exc.kind}): {exc}",
        )
        return exit_codes.BLOCKED
    data = {
        "server": config.source,
        "identity": ident,
        "live_operations": ["animation.retime", "scene.audit", "scene.checkpoint", "scene.inspect"],
    }
    human = [
        f"live session: {ident.get('blend_path') or '(unsaved scene)'}",
        f"  project {ident.get('project_id')!r}, shot {ident.get('shot_id')!r}, revision {ident.get('revision')}, dirty: {ident.get('is_dirty')}",
        f"  runtime {ident.get('runtime_version')} on Blender {ident.get('blender_version')} (server: {config.source})",
    ]
    _emit(data, as_json=args.json, human="\n".join(human))
    return exit_codes.OK


def cmd_capabilities(args: argparse.Namespace) -> int:
    try:
        project = _project(args)
    except ProjectError as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    path = project.root / "state" / "diagnostics" / "capabilities.json"
    if not path.exists():
        _emit(
            {"error": "no capabilities.json; run `fluidblend doctor --project .`"},
            as_json=args.json,
            human="no diagnostic yet; run `fluidblend doctor --project .`",
        )
        return exit_codes.BLOCKED
    _emit(read_json(path), as_json=args.json)
    return exit_codes.OK


def cmd_preview(args: argparse.Namespace) -> int:
    """Serve a published web game folder on 127.0.0.1 and open it: a browser refuses GLB over file://."""
    import time
    import webbrowser

    from fluidblend.core.paths import resolve_inside
    from fluidblend.hostops.game_web import is_web_game, served

    try:
        project = _project(args)
        folder = resolve_inside(project.root, args.game_dir, allow_missing=False)
    except (ProjectError, ValueError, OSError) as exc:
        _emit({"error": str(exc)}, as_json=args.json, human=f"error: {exc}")
        return exit_codes.INVALID
    if not is_web_game(folder) or not (folder / "assets" / "character.glb").is_file():
        message = "game_dir is not a web game folder published by game.import_test (template web)"
        _emit({"error": message}, as_json=args.json, human=f"error: {message}")
        return exit_codes.INVALID
    with served(folder) as base:
        url = f"{base}/index.html"
        _emit({"url": url}, as_json=args.json, human=f"serving {folder}\n  {url}\nCtrl+C to stop")
        if not args.no_open:
            webbrowser.open(url)
        try:
            deadline = time.monotonic() + args.seconds if args.seconds else None
            while deadline is None or time.monotonic() < deadline:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
    return exit_codes.OK


# --- Parser ---------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fluidblend",
        description="fluidblend engine: AI-drivable Blender production (headless batch, typed operations, evidence).",
        epilog="Exit codes:\n" + EXIT_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"fluidblend {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser, *, project_required: bool = True) -> None:
        p.add_argument("--project", required=project_required, help="root of the production project")
        p.add_argument("--json", action="store_true", help="structured JSON output")

    p = sub.add_parser(
        "doctor",
        help="diagnose the workstation and its capabilities (read-only; writes capabilities.json with --project)",
    )
    add_common(p, project_required=False)
    p.add_argument("--no-probe", action="store_true", help="do not launch Blender for the probe")
    p.add_argument(
        "--live", action="store_true", help="probe the configured MCP server (list_tools + get_scene_info)"
    )
    p.add_argument(
        "--write-lock", metavar="PATH", help="write dependencies.lock.json from the observed capabilities"
    )
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("init", help="create or complete a project (idempotent, never overwrites)")
    p.add_argument("--path", required=True)
    p.add_argument("--profile", choices=["film", "game", "hybrid"], default="film")
    p.add_argument("--project-id")
    p.add_argument("--name")
    p.add_argument("--game-engine", choices=["godot", "web", "unreal", "none"], default="none")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 3 if conflicts are detected")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("inspect", help="inspect manifests, versions, revisions and tasks")
    add_common(p)
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("plan", help="plan a request without mutating anything")
    add_common(p)
    p.add_argument("--request", required=True, help="request JSON file (relative to the project or absolute)")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="run a typed operation")
    p.add_argument(
        "--mode",
        choices=["batch", "live"],
        default="batch",
        help="batch: dedicated Blender process (default); live: the open Blender session through MCP (scene.inspect, scene.audit, animation.retime, scene.checkpoint)",
    )
    add_common(p)
    p.add_argument("--operation", required=True, help="request JSON file")
    p.add_argument("--dry-run", action="store_true", help="force dry_run=true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("task", help="task state, cancellation and reconciliation")
    add_common(p)
    task_sub = p.add_subparsers(dest="task_command", required=True)
    for name in ("status", "cancel", "reconcile"):
        tp = task_sub.add_parser(name)
        tp.add_argument("--id", required=True)
    task_sub.add_parser("list")
    p.set_defaults(func=cmd_task)

    p = sub.add_parser("validate", help="technical validation of a shot (shot.validate)")
    add_common(p)
    p.add_argument("--target", required=True, help="shot_id")
    p.add_argument("--no-preview", action="store_true", help="do not require a published preview")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("resume", help="rebuild the state from the journal and list what can be resumed")
    add_common(p)
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("revision", help="revisions of the protected sources")
    add_common(p)
    rev_sub = p.add_subparsers(dest="revision_command", required=True)
    rp = rev_sub.add_parser("accept", help="accept a detected manual change")
    rp.add_argument("--target", required=True, help="shot_id")
    rev_sub.add_parser("list")
    p.set_defaults(func=cmd_revision)

    p = sub.add_parser("ops", help="list the operations and their availability")
    p.add_argument("--all", action="store_true", help="include the unavailable operations (P1/P2)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_ops)

    p = sub.add_parser("schema", help="export/check the JSON Schemas")
    schema_sub = p.add_subparsers(dest="schema_command", required=True)
    for name in ("export", "check"):
        sp = schema_sub.add_parser(name)
        sp.add_argument("--out", default="schemas")
        sp.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("client-config", help="generate/merge the MCP configuration of a client")
    p.add_argument("--client", choices=["claude", "codex", "vscode"], required=True)
    p.add_argument("--name", default="blender")
    p.add_argument("--port", type=int, default=9876)
    p.add_argument("--host", default="localhost")
    p.add_argument("--no-safe-mode", action="store_true")
    p.add_argument("--write", help="file to create/merge (otherwise printed to stdout)")
    p.set_defaults(func=cmd_client_config)

    p = sub.add_parser("runtime", help="install or check the runtime add-on used by live mode")
    runtime_sub = p.add_subparsers(dest="runtime_command", required=True)
    rp = runtime_sub.add_parser(
        "install", help="copy the runtime into the Blender user add-ons directory (hash-checked)"
    )
    rp.add_argument(
        "--enable", action="store_true", help="also enable it in the Blender preferences (headless)"
    )
    rp.add_argument("--force", action="store_true")
    rp.add_argument("--json", action="store_true")
    sp = runtime_sub.add_parser("status")
    sp.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_runtime)

    p = sub.add_parser("live", help="live session (open Blender through MCP)")
    add_common(p)
    live_sub = p.add_subparsers(dest="live_command", required=True)
    live_sub.add_parser("status", help="identity of the open session: file, project, revision, dirty flag")
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("preview", help="play a published game folder yourself")
    preview_sub = p.add_subparsers(dest="preview_cmd", required=True)
    wp = preview_sub.add_parser("web", help="serve a web game folder on 127.0.0.1 and open the browser")
    add_common(wp)
    wp.add_argument(
        "--game-dir", required=True, help="game folder published by game.import_test, project-relative"
    )
    wp.add_argument("--no-open", action="store_true", help="print the URL without opening a browser")
    wp.add_argument("--seconds", type=float, default=0, help="stop after this long (0 = until Ctrl+C)")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("capabilities", help="show the latest capabilities.json of the project")
    add_common(p)
    p.set_defaults(func=cmd_capabilities)
    return parser


def _utf8_output() -> None:
    """Redirected, Windows writes the ANSI code page: `Démo` reached an agent reading the pipe as
    UTF-8 as `D�mo`, and a command it copied from `next_safe_actions` named a folder that does
    not exist. The output is UTF-8 whatever it is written to."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return exit_codes.UNKNOWN_STATE


if __name__ == "__main__":
    sys.exit(main())
