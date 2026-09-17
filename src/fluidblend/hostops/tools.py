"""`tool.inspect` and `tool.register`: a declaration becomes a capability only through its own tests."""

from fluidblend.contracts.common import ErrorCode
from fluidblend.contracts.production import ADJUSTMENT_TOOLS, ToolRegistration
from fluidblend.core.atomic import read_json
from fluidblend.core.custom_tools import limitations, load_tool, tool_dir
from fluidblend.core.evidence import verify_evidence
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import relpath_posix
from fluidblend.core.production import admitted_path
from fluidblend.core.revisions import RevisionStore
from fluidblend.hostops.context import HostOpError


def _load(ctx):
    try:
        return load_tool(ctx.project, ctx.params.tool_id)
    except ValueError as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, str(exc)) from exc


def inspect(ctx):
    tool, path = _load(ctx)
    limits = limitations(tool)
    registration_path = tool_dir(ctx.project, tool.tool_id) / "registration.json"
    status = "unsupported" if limits else "declared"
    if not limits and registration_path.is_file():
        registered = ToolRegistration.model_validate(read_json(registration_path))
        status = "registered" if registered.tool_sha256 == sha256_file(path) else "registration_stale"
    ctx.write_report(
        "tool-inspection.json",
        {
            "tool": tool.model_dump(mode="json"),
            "tool_sha256": sha256_file(path),
            "status": status,
            "limitations": limits,
            # What the declaration inherits and cannot change.
            "base_contract": ADJUSTMENT_TOOLS.get(tool.base_tool),
            "usable": status == "registered",
        },
    )
    ctx.metrics.update({"tool_id": tool.tool_id, "status": status, "limitations": limits})
    if limits:
        ctx.warnings.append("this declaration cannot be tested or registered: " + "; ".join(limits))
    elif status != "registered":
        ctx.next_safe_actions.append("tool.test on a shot that shows the problem, then tool.register")


def register(ctx):
    tool, path = _load(ctx)
    limits = limitations(tool)
    if limits:
        raise HostOpError(ErrorCode.UNSUPPORTED_CAPABILITY, "; ".join(limits), recovery="see tool.inspect")
    report_path = admitted_path(ctx.project, ctx.params.test_report_path)
    report = read_json(report_path)
    revision = RevisionStore(ctx.project.root).get(f"shot:{report.get('shot_id')}")
    if revision is None:
        raise HostOpError(ErrorCode.SCENE_CONFLICT, "the tested shot has no recorded revision")
    ok, reason = verify_evidence(
        report_path,
        project_id=ctx.project.project_id,
        shot_id=report["shot_id"],
        revision=revision.revision,
        scene_sha256=revision.sha256,
    )
    if not ok:
        raise HostOpError(
            ErrorCode.SCENE_CONFLICT, f"tool test report: {reason}", recovery="run tool.test again"
        )
    if report.get("tool_id") != tool.tool_id or report.get("tool_sha256") != sha256_file(path):
        raise HostOpError(
            ErrorCode.SCENE_CONFLICT, "tool.json changed since it was tested", recovery="run tool.test again"
        )
    results = report.get("results", [])
    failed = [r["name"] for r in results if not r.get("passed")]
    if failed or not report.get("all_passed") or {r["name"] for r in results} != {t.name for t in tool.tests}:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "a tool is registered only when every declared test passed",
            details={"failed": failed, "declared": [t.name for t in tool.tests]},
        )
    destination = tool_dir(ctx.project, tool.tool_id) / "registration.json"
    if destination.is_file():
        current = ToolRegistration.model_validate(read_json(destination))
        if current.version >= tool.version:
            raise HostOpError(
                ErrorCode.SCENE_CONFLICT,
                f"version {current.version} is already registered; bump tool.json version to register a change",
            )
    registration = ToolRegistration(
        tool_id=tool.tool_id,
        version=tool.version,
        base_tool=tool.base_tool,
        supported_rigs=tool.supported_rigs,
        bounds=tool.bounds,
        tool_sha256=sha256_file(path),
        test_report=relpath_posix(ctx.project.root, report_path),
        test_report_sha256=sha256_file(report_path),
        tests_passed=len(results),
    )
    ctx.write_report("registration.json", registration.model_dump(mode="json"))
    ctx.metrics.update({"tool_id": tool.tool_id, "version": tool.version, "tests_passed": len(results)})
