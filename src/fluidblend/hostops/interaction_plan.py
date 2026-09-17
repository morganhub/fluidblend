"""Derive a reviewable hand-off choreography; the scene is only touched by `interaction.apply`."""

from fluidblend.contracts.production import InteractionPlan


def run(ctx):
    params = ctx.params
    start, end = params.frame_range.start, params.frame_range.end_exclusive
    handoff, overlap = params.handoff_frame, params.overlap_frames
    giver, receiver = params.giver.instance_id, params.receiver.instance_id
    shared = {"start": handoff - overlap, "end_exclusive": handoff + overlap + 1}
    plan = InteractionPlan(
        **params.model_dump(),
        shot_id=ctx.request.target.shot_id,
        windows=[
            {
                "name": "giver_holds",
                "participant": giver,
                "grip": "primary",
                "frame_range": {"start": start, "end_exclusive": handoff},
            },
            {"name": "shared_hold", "participant": giver, "grip": "primary", "frame_range": shared},
            {"name": "shared_hold", "participant": receiver, "grip": "secondary", "frame_range": shared},
            {
                "name": "receiver_holds",
                "participant": receiver,
                "grip": "secondary",
                "frame_range": {"start": handoff, "end_exclusive": end},
            },
        ],
        ownership=[
            {"owner_instance_id": giver, "frame_range": {"start": start, "end_exclusive": handoff}},
            {"owner_instance_id": receiver, "frame_range": {"start": handoff, "end_exclusive": end}},
        ],
        events=[
            {"name": "reach-start", "frame": start},
            {"name": "contact", "frame": handoff - overlap},
            {"name": "handoff", "frame": handoff},
            {"name": "release", "frame": handoff + overlap},
            {"name": "settle", "frame": end - 1},
        ],
    )
    ctx.write_report("interaction-plan.json", plan.model_dump(mode="json"))
    ctx.metrics.update({"interaction_id": params.interaction_id, "windows": len(plan.windows)})
    ctx.warnings.append(
        "plan not checked against the scene: interaction.apply verifies instances, reach and channel ownership"
    )
    ctx.next_safe_actions.append(
        "review interaction-plan.json, then run interaction.apply with its plan_path"
    )
