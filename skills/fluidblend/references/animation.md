# Animation

Status: **partially implemented**.

- Lot P0: `animation.retime` (a slower or faster variant of a clip).
- Bounded P1: `animation.create`, `animation.apply`, `animation.loop`, `animation.bake`.
- Unavailable: `animation.retarget`, Rigify walk and take/give recipes.

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
`stage` (blocking/spline/polish) and optional `profile_path`. Presets: `idle_neutral`, `turn`,
`look_at`, `reach`, `react`. It creates an unassigned Action with a slot and manifest; it does
not replace active animation. The recorded seed makes the bounded recipe repeatable.
Blocking affects newly authored keys only. Polish is currently a stage label, not automatic polish.

`animation.apply` takes `clip_id`, `start_frame`. It uses a REPLACE NLA track and rejects any
channel overlap with existing active/NLA animation. Shared-channel priority blending is not yet
supported. `animation.loop` takes target `clip_id`, `output_clip`, `repetitions`; it verifies
endpoint curve values before adding repetition. This is not a physical contact/velocity test.

`animation.bake` takes `output_clip`, `frame_range`, `step` and creates an export variant.
It removes constraints and drivers only in that variant, checks mesh deformation within 1 mm
at first/middle/last frames, and preserves the source. Baked rigs cannot accept control recipes.
Indexes at `animation/clips/<id>/clip.json` cite versioned blend/report hashes. Contacts and events
are initially empty; do not claim measured locomotion or hand contact from these clips.

Retargeting, walk, take/give and support-relative contact cleanup remain unavailable. Reject such
requests without improvised scripts. Optional retarget add-ons remain external, never vendored.
