# Animation

Status: **partially implemented**.

- Lot P0: `animation.retime` (a slower or faster variant of a clip).
- Bounded P1: `animation.create`, `animation.apply`, `animation.loop`, `animation.bake`.
- Bounded P1: `animation.retarget`, one preset (`simple_biped_to_rigify`), never a universal solver.

## Slotted Actions: the only allowed API

Blender 5.0 removed `Action.fcurves`, `Action.groups` and `Action.id_root`. The access path is:

```
Action → layers → strips (type KEYFRAME) → channelbag(slot) → fcurves
```

Everything goes through `blender_runtime/fluidblend_runtime/anim/slotted.py`, the repository's only
access point to F-curves. A guard test (`tests/unit/test_no_legacy_action_api.py`) forbids using the
legacy API anywhere else. An Action assigned without a slot (`animation_data.action_slot is None`) is
an audit **error**, not a detail: the channels are then connected to nothing.

Time conventions: the contracts use `FrameRange {start, end_exclusive}`; Blender receives inclusive
`frame_start` / `frame_end`. `end_exclusive = 241` means 240 frames. The frame rate is rational
(`{numerator, denominator}`), 24/1 by default.

## What `scene.build` produces

Each character gets an Action named `<instance_id>.<clip_id>` (by default `hero-01.walk`)
containing:

- 11 pose channels: thigh, shin, arm and forearm rotations, pelvis sway, counter-rotation of the
  chest and head;
- a 48-frame cycle, each F-curve carrying a `CYCLES` F-modifier set to `REPEAT` before and after;
- a linear global translation on the armature object's `location[1]`, from frame 1 to the last frame
  of the shot (speed 0.4 m/s x the instance scale);
- two contact pose markers: `contact_L` at `1 + phase_offset`, `contact_R` half a period later;
- `use_fake_user = True`: the Action survives even when nothing uses it any more.

The phase offset (`phase_offset_frames` in `shot.json`, 12 frames for `sidekick-01`) keeps the two
characters from walking in lockstep.

## `animation.retime`

Creates a **variant** of the Action and leaves the source intact. Full request:

```json
{
  "schema_version": "1.0",
  "operation": "animation.retime",
  "operation_id": "retime-shot010-hero-001",
  "project_id": "demo-studio",
  "target": {"shot_id": "shot010", "instance_id": "hero-01", "clip_id": "walk", "expected_revision": 1},
  "parameters": {
    "duration_scale": 1.2,
    "preserve_contact_markers": true,
    "output_variant": "walk-slower-v001",
    "preview_samples": 8
  },
  "dry_run": false
}
```

| Parameter | Bounds | Meaning |
| --- | --- | --- |
| `duration_scale` | > 0.05 and <= 20 | multiplies the **duration**. 1.2 = 20 % longer, therefore slower |
| `preserve_contact_markers` | boolean, default `true` | pose markers follow the keys |
| `output_variant` | lowercase identifier | name of the variant, yields the Action `<instance_id>.<variant>` |
| `preview_samples` | 0 to 64, default 8 | Workbench images rendered before **and** after, at half resolution |

`target.instance_id` and `target.clip_id` are mandatory. If the clip assigned to the instance does
not match `clip_id`, the operation refuses with `SCENE_CONFLICT`: inspect the scene and fix the
request, do not force it.

Sequence:

1. render the "before" images (when `preview_samples > 0`);
2. copy the Action, scale the times of every key, Bézier handles, restricted F-modifier ranges, pose
   markers and the Action range, around the first key;
3. assign the variant and its slot to the instance; the source gets `use_fake_user` and stays in the
   file;
4. render the "after" images;
5. duration check: if the deviation from `duration x duration_scale` exceeds 0.5 frame, the
   operation fails;
6. increment the scene identity and save a new work version.

Reference measurement (acceptance scenario A08): 48 frames x 1.2 → 57.6 frames; contact markers 1
and 25 → 1 and 30; source `v001` unchanged (identical hash); new revision 2.

Published artifacts: `shots/<shot>/work/v002/<shot>.blend`, then, in
`reviews/<shot>/<operation_id>/`: `retime-report.json` (before/after, durations, markers, measured
error, `source_action_intact`) and the `review/before/` and `review/after/` folders.

Properties set on the variant: `fluidblend_clip_id`, `fluidblend_source_clip`,
`fluidblend_source_action`, `fluidblend_duration_scale`.

## Pitfalls

- **Direction of `duration_scale`**: it is a duration, not a speed. For "twice as fast", pass `0.5`.
  The report restates the convention on every run.
- **Revision**: `expected_revision` must reflect the current revision. After a first retime the
  revision becomes 2; re-running with `expected_revision: 1` gives `SCENE_CONFLICT`.
- **A reused `operation_id`** with different parameters gives `SCENE_CONFLICT`. For a second attempt
  with another factor, change both `operation_id` **and** `output_variant`.
- **Cost of the previews**: `preview_samples` counts twice (before + after) in the budget estimate.
  Pass 0 for a fast retime with no visual evidence — and say so in the report.
- **Cycle and root motion**: the scaling applies to the Action's keys. Since the global translation
  is also a key of the Action, it is stretched along with the rest; the ground speed therefore
  changes accordingly. Do not promise a foot that does not slide: slide measurement is a P1 check.

## Bounded Rigify library

`animation.create` takes `preset`, `output_clip`, `frame_range`, `amplitude` (0–0.6), `seed`,
`stage` (blocking/spline/polish) and optional `profile_path`. Presets: `idle_neutral`, `walk`,
`turn`, `look_at`, `reach`, `take_prop`, `give_prop`, `react`. It creates an unassigned Action with a slot and manifest; it does
not replace active animation. The recorded seed makes the bounded recipe repeatable.
Blocking affects newly authored keys only. Polish is currently a stage label, not automatic polish.

`animation.apply` takes `clip_id`, `start_frame`. It uses a REPLACE NLA track and rejects any
channel overlap with existing active/NLA animation. Shared-channel priority blending is not yet
supported. `animation.loop` takes target `clip_id`, `output_clip`, `repetitions`; it verifies
endpoint curve values before adding repetition. This is not a physical contact/velocity test.

`animation.bake` takes `output_clip`, `frame_range`, `step`, `rigid_limbs` and creates an export
variant. It removes constraints, drivers and control-rig NLA tracks only in that variant (their
Actions stay in the file), names the clip `<rig>.<output_clip>`, checks mesh deformation within 1 mm
at five frames (ends and quarters), and preserves the source. Baked rigs cannot accept control recipes.

A Rigify character needs `"rigid_limbs": true`. Blender's IK solver compresses a stretchy limb before
it bends it; the deform bones then carry a non-uniform scale that shears their children, which
neither TRS keys nor glTF can hold (measured: 13.8 mm at the feet). Without the option the bake is
refused and names the bones (`non_uniform_scale_bones`, `hint`). With it, IK stretch is disabled in
the new version only, so knees and elbows bend instead: the report states `max_pose_delta_m`
(35.8 mm on the walk fixture, at the knees) and refuses if an IK tip leaves its target by more than
1 mm (`ik_tip_drift_m`). Say it plainly: the baked pose is not the control-rig pose, contacts are kept.
Indexes at `animation/clips/<id>/clip.json` cite versioned blend/report hashes. Only `walk` and
`take_prop` declare contacts; do not claim measured locomotion or hand contact from the other clips.

### `take_prop` and `give_prop`

Both move one palm (`hand`: `left` | `right`, default `right`) with the arm IK: reach over the first
3/8 of `frame_range` (at least 16 frames), hold still until 5/8, return. `amplitude` and `seed` are
ignored; `stage: blocking` is refused.

- `take_prop` needs `prop_instance_id`: a **static** prop of kind `prop` in the scene. The target is
  its `primary` grip. The clip declares a contact window whose support is that prop and records
  `contact_error` / `contact_slide` in the prop's space (gate `contact_error_max_m`).
- `give_prop` needs `target_point` (world, metres). It records a world-space `contact_error` against
  that point and declares no contact.

The control point is the palm (`DEF-hand.R@0.5`), not the IK control. A target beyond 95 % of the arm
length is refused with `needed_m` / `arm_m`. The hand moves, the prop does not: passing a prop from
one character to another is `interaction.apply` ([interactions.md](interactions.md)).
Examples: [request-animation-create-walk.json](../assets/request-animation-create-walk.json),
[request-animation-create-take-prop.json](../assets/request-animation-create-take-prop.json).

### `walk` and the shared measurements

`walk` authors one root-motion cycle on the IK feet: stride per cycle = `2 x amplitude` metres
(amplitude >= 0.05), even `frame_range` of at least 16 frames, `stage: blocking` refused (constant
interpolation cannot hold a contact). The manifest records `root_motion: root_bone`,
`root_motion_channels`, `stride_m`, two contact windows (`left_foot`, `right_foot`) and `measurements`.

Every measurement states `kind`, `effector`, `control_point` (the **deform** bone, not the control),
`space`, `frame_range`, `sampling_step`, `value`, `unit`, `tolerance` and `passed`:

| Kind | Definition | Gate |
| --- | --- | --- |
| `foot_slide` | largest 3D distance from the first sample of the support window, world space, every frame | `quality.foot_slide_max_m` (0.02 m) |
| `loop_pose` | largest control-point distance between first and last frame, root motion removed | `quality.loop_pose_error_max` |
| `loop_velocity` | seam velocity mismatch in m/frame | none: `passed` is `null`, never quote it as a pass |

`animation.loop` repeats root-motion channels with an accumulating offset and re-measures the seam
on the evaluated rig. `animation.apply` re-measures **every contact window of every repetition in
the assembled scene** and checks the root travel against `stride_m x repetitions`; a failed
measurement refuses the operation and publishes nothing. A root-motion strip holds forward after its
end so the character does not snap back.

Limits to state: straight walk on flat static ground, ankle control point, no heel roll, no arm
swing, linear stance/swing keys. It is a technical contact measurement, not an approved gait.

## Bounded retargeting: `animation.retarget`

One preset, `simple_biped_to_rigify`: a clip played by a P0 biped (`fluidblend.simple_biped/1`) is
transferred onto the FK controls of a `rigify/0.6.10` character **of the same shot** (add it with
`shot.build`). Example: [request-animation-retarget.json](../assets/request-animation-retarget.json).
Target: `shot_id` + the Rigify `instance_id`. Parameters: `source_instance_id`, `source_clip` (must
be the clip really assigned to the source, else `SCENE_CONFLICT`), `output_clip`, `frame_range`
(2–600 frames), `test_poses` (2–9).

How: rotations are transferred as **deltas from each rig's own rest pose**, in character space, so
arms-down against an A-pose needs no manual alignment. A few poses are transferred and measured
first; if one fails, the full range is not attempted. The result is a **new library clip** (FK
rotations, arm and leg `IK_FK` held at 1, root travel scaled by the leg-length ratio, source contact
markers copied as events), indexed like any other clip; apply it with `animation.apply`. The source
Action is only evaluated, never edited.

Gates: each limb's end, measured on the target's **deform** bone, must point within
`quality.retarget_limb_error_max_deg` (3°) of where the source deltas send it, on every frame — an
FK control that drives nothing is caught; and the source limbs must really swing (≥ 1°), so a
motionless source cannot pass with a perfect zero.

Refuse plainly, do not look for a workaround: any other pair of rigs (`RIG_MAPPING_REQUIRED` — Mixamo,
mocap, another Rigify version, a baked skeleton), a source that does not play `source_clip`. Limits
to state: `spine` and `neck` of the source are dropped; **feet are not re-planted**, so foot slide is
neither measured nor promised (use `contact_lock` on a marked stance afterwards); no fingers, face
or props; a technical transfer check, not an approval of the motion on the new body.

Contact cleanup beyond `contact_lock` remains unavailable. Optional retarget add-ons remain
external, never vendored.
