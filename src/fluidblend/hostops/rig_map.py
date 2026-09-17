from fluidblend.contracts.common import ErrorCode
from fluidblend.contracts.production import RigProfile
from fluidblend.core.atomic import read_json
from fluidblend.core.evidence import verify_evidence
from fluidblend.core.production import RIGIFY_CONTROLS, admitted_path
from fluidblend.core.revisions import RevisionStore
from fluidblend.hostops.context import HostOpError


def run(ctx):
    path = admitted_path(ctx.project, ctx.params.inspection_path)
    revision = RevisionStore(ctx.project.root).get(f"shot:{ctx.request.target.shot_id}")
    if revision is None:
        raise HostOpError(ErrorCode.SCENE_CONFLICT, "no revision for rig inspection")
    ok, reason = verify_evidence(
        path,
        project_id=ctx.project.project_id,
        shot_id=ctx.request.target.shot_id,
        revision=revision.revision,
        scene_sha256=revision.sha256,
    )
    if not ok:
        raise HostOpError(ErrorCode.SCENE_CONFLICT, reason)
    inspection = read_json(path)
    if inspection.get("instance_id") != ctx.request.target.instance_id:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "inspection belongs to another character")
    controls = dict(RIGIFY_CONTROLS)
    if set(ctx.params.controls) - set(controls):
        raise HostOpError(ErrorCode.VALIDATION_FAILED, "unknown semantic control")
    controls.update(ctx.params.controls)
    names = {b["name"] for b in inspection.get("bones", [])}
    controls = {role: name if name in names else None for role, name in controls.items()}
    missing = [role for role, name in controls.items() if name is None]
    profile = RigProfile(
        profile_id=ctx.params.profile_id,
        controls=controls,
        missing_controls=missing,
        unsupported_operations=["rig.validate", "animation.create"] if missing else [],
        source_sha256=revision.sha256,
        instance_id=inspection["instance_id"],
    )
    ctx.write_report("rig-profile.json", profile.model_dump())
    ctx.metrics.update({"mapped_controls": len(controls) - len(missing), "missing_controls": missing})
    if missing:
        ctx.warnings.append("incomplete mapping; dependent operations must refuse")
