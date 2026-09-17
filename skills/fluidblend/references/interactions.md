# Interactions between characters

Status: **bounded prop hand-off implemented** (`interaction.plan`, `interaction.apply`,
`interaction.validate`), acceptance B03. Nothing else is: no handshake, no shared gaze, no body
contact, no two-handed carry, no walking hand-off. For those, stop and say so.

## What the hand-off does

One rigid prop, two Rigify characters standing still, one ownership transfer.

1. `interaction.plan` (host, no Blender) turns the parameters into a reviewable
   `interaction-plan.json`: windows (`giver_holds`, `shared_hold` for both hands, `receiver_holds`),
   ownership order and events. It does **not** look at the scene and says so in a warning. Review it.
2. `interaction.apply` (Blender, new work version) checks the scene, then:
   - the giver's palm reaches the meeting point (`meeting_point`, else the midpoint of the two
     hand-side shoulders lowered by 0.2 m), holds `overlap_frames` on each side of `handoff_frame`,
     returns;
   - the prop is attached to the giver's hand bone from the first frame, primary grip in the palm;
   - the receiver's palm reaches the prop's **secondary** grip where it really is at the hand-off;
   - ownership moves at `handoff_frame` between two `CHILD_OF` constraints whose influences are
     keyed constant; the receiver's inverse matrix is computed so the prop keeps its world
     transform across the switch;
   - the measurements below gate the write. A failure publishes nothing.
3. `interaction.validate` (Blender, read) re-runs the same measurements on the current scene.

```powershell
fluidblend run --project . --operation requests/interaction-plan.json
# review reviews/<shot>/<operation_id>/interaction-plan.json
fluidblend run --project . --operation requests/interaction-apply.json     # parameters.plan_path
fluidblend run --project . --operation requests/interaction-validate.json  # parameters.interaction_id
```

Examples: [request-interaction-plan.json](../assets/request-interaction-plan.json),
[request-interaction-apply.json](../assets/request-interaction-apply.json),
[request-interaction-validate.json](../assets/request-interaction-validate.json).

## Prerequisites

- Both characters come from `shot.build` with the `rigify/0.6.10` profile; a baked export skeleton
  is refused. Explicit `profile_path` mappings are not supported here.
- The prop is an asset of `kind: "prop"`: `root_object`, no armature, `grips` with at least
  `primary` and, for a hand-off, `secondary` (prop local space, metres). Unit scale only.
- Place the characters facing each other within arm's reach (`shot.build` `location` and
  `rotation_z`, radians). On the reference character, 0.7 m apart works; a target beyond 95 % of
  the arm length is refused with the measured distances — move the characters, do not force it.
- The prop must have **no other authority**: no parent, no constraint, no animation.
  Otherwise `SCENE_CONFLICT`, and nothing is changed.
- The hand channels (`hand_ik` location, arm `IK_FK`) must be free on both characters, as for any
  `animation.apply`.

## Refusals you will meet

| Situation | Answer |
| --- | --- |
| plan made on another revision, or edited after it was written | `SCENE_CONFLICT` (exit 3) at preflight: plan again on the current revision, review, apply |
| meeting point or grip beyond reach | `VALIDATION_FAILED`, details `needed_m` / `arm_m` |
| prop already parented, constrained or animated; interaction id already applied | `SCENE_CONFLICT` |
| participant missing, not an armature, or prop not of kind `prop` | `VALIDATION_FAILED` |
| hand channels already owned by a clip | `SCENE_CONFLICT` with the overlapping channels |

## Measurements (shared with the clip library)

Every record states `kind`, `effector`, `control_point`, `space`, `frame_range`, `sampling_step`,
`value`, `unit`, `tolerance`, `passed`. The control point is the **palm**, halfway along the hand
deform bone (`DEF-hand.R@0.5`), not the IK control. Contacts are expressed **in the prop's space**,
every frame of the window.

| Kind | Meaning | Gate (`config/quality.json`) |
| --- | --- | --- |
| `contact_error` | largest palm-to-grip distance in the window | `contact_error_max_m` (0.02 m) |
| `contact_slide` | largest palm drift from the window's first frame | `contact_error_max_m` |
| `handoff_jump` | largest prop displacement between frames h-1, h, h+1 | `handoff_jump_max_m` (0.005 m) |
| `handoff_rotation_jump` | same for rotation | `handoff_rotation_jump_max_rad` (0.01) |

Two checks complete them: `single_authority` (at every frame exactly the planned constraint has
influence 1, no parent, no other constraint, no transform curve on the prop) and
`no_constraint_cycle` (no participant bone is constrained to the prop or to the other character).

Be precise about what is a real test. While a hand **owns** the prop, its contact is true by
construction. The informative figures are the receiver's `shared_hold` before the hand-off, the
giver's `shared_hold` after it, and the jump.

`interaction.validate` exits 0 even when the measurements fail: read `metrics.technical_pass` and
`interaction-validation.json`. A failed validation after a human edit or a timing change is reported
and the edit is preserved; the kit never repairs it silently. Re-timing one participant is **not**
propagated to the other or to the prop: validate afterwards and report the breaks.

## Hand recipes without ownership

`animation.create` presets `take_prop` (`prop_instance_id`, `hand`) and `give_prop`
(`target_point`, `hand`) author the same palm reach as library clips for a **static** prop or a
world point. The hand moves; the prop does not. `animation.apply` re-measures the contact against
the prop instance in the assembled scene. See [animation.md](animation.md).

## Limits to state every time

Stationary characters, rigid prop, open hands (no finger pose), no wrist orientation change, no
intersection test between bodies and prop, one transfer per interaction. `technical_pass` is a
measurement, not an approval of the gesture: art validation stays human and cites the frames looked at.
