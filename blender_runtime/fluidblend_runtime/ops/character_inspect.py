from fluidblend_runtime.production import character, skin_report


def run(ctx, request, builder):
    rig = character(request)
    report = {
        "instance_id": request["target"]["instance_id"],
        "armature": rig.name,
        "rig_profile": rig.get("fluidblend_rig_profile"),
        **skin_report(rig),
    }
    if request["parameters"].get("include_bones", True):
        report["bones"] = [
            {
                "name": b.name,
                "parent": b.parent.name if b.parent else None,
                "deform": b.use_deform,
                "head": list(b.head_local),
                "tail": list(b.tail_local),
            }
            for b in rig.data.bones
        ]
    builder.write_report("character-inspection.json", report)
    builder.metrics.update({k: report[k] for k in ("skinned", "problematic_scales", "uninfluenced_vertices")})
