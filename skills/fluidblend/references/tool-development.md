# Adjustment tools generated on demand

## Status: two built-in tools, declarative custom tools

`adjustment.preview`, `adjustment.apply` and `adjustment.revert` are available with **two** built-in
tools chosen by `parameters.tool`: `contact_lock` (acceptance B05; the default when `tool` is
omitted) and `look_at_target`. `tool.inspect`, `tool.test` and `tool.register` manage
**declarative** custom tools (acceptance B08): a custom tool narrows a built-in tool and proves it
with tests. It never brings code: the kit loads no script from `tools/custom/`, and you write none
there. The Director panel in Blender's sidebar runs the same three operations for `contact_lock`; after
a preview it draws the effector path today (red) and fixed (green) over the viewport, from the
`viewport` block of `adjustment-preview.json`, without changing the session.

### `contact_lock`

"Fix the sliding foot", "keep the hand on this handle" — over a **marked stance window**, for one IK
effector (`left_foot`, `right_foot`, `left_hand`, `right_hand`) of a `rigify/0.6.10` character.

```powershell
fluidblend run --project . --operation requests/adjustment-preview.json   # saves nothing
fluidblend run --project . --operation requests/adjustment-apply.json     # same parameters, new version
fluidblend run --project . --operation requests/adjustment-revert.json    # parameters.adjustment_id
```

Parameters: `adjustment_id`, `effector`, `frame_range`, optional `support_instance_id` (hold the
contact in that instance's space instead of the world), `blend_frames` (1–24, default 3),
`max_correction_m` (≤ 0.5, default 0.15), `preview_samples` (0–16, preview only). Target: shot and
`instance_id`. Examples: [preview](../assets/request-adjustment-preview.json),
[apply](../assets/request-adjustment-apply.json), [revert](../assets/request-adjustment-revert.json).

How it works: the anchor is the control point (deform bone, palm for a hand) at the first frame of
the window. The tool adds **one Action on one additive NLA track** keying the IK control's location;
it edits no source Action or strip. `revert` removes exactly that track and Action, in a new version,
and reports the restored drift. If someone changed the layer by hand, `revert` answers
`SCENE_CONFLICT` and leaves it as found.

It refuses instead of guessing:

| Situation | Answer |
| --- | --- |
| drift already within tolerance | `VALIDATION_FAILED` "nothing to lock" |
| drift above `max_correction_m` (the window contains a step) | `VALIDATION_FAILED` "travel, not a sliding stance": narrow the window, never raise the bound to force it |
| limb in FK inside the window | `VALIDATION_FAILED` |
| result still above tolerance after three passes (`apply`) | `VALIDATION_FAILED`, nothing published |
| `adjustment_id` already applied | `SCENE_CONFLICT` |

Reports (`adjustment-preview.json`, `adjustment-apply.json`) carry `before` and `after` measurement
records (space, window, control point, tolerance — same format as the clip library), and the
preview adds `review/before` and `review/after` frames rendered through the shot camera as it is
framed, plus `review/closeup-before` and `review/closeup-after`: top-down close-ups clipped just above
the effector, over a red cross fixed at the contact anchor. Look at those first — a 10 cm slide is
invisible on a whole-body frame, obvious against the cross. `technical_pass` is a contact measurement; look at the frames and say which ones you looked
at before calling the fix good. Limits: translation only (no foot roll, no wrist orientation), the
other contacts of the character are not re-planted, one effector per adjustment.

### `look_at_target`

"Make her look at the baton while she walks" — the **head** of a `rigify/0.6.10` character turns
towards a world point or an instance over a marked window. Same three operations, same lifecycle,
`"tool": "look_at_target"` is mandatory. Example: [preview](../assets/request-adjustment-preview-look-at.json).

Parameters: `adjustment_id`, `tool`, `frame_range`, exactly one of `target_point` (world, metres)
and `target_instance_id` (its origin, followed on every frame), `blend_frames` (1–48, default 8),
`max_angle_deg` (≤ 80, default 60), `max_step_deg` (≤ 45, default 12), `preview_samples`.

How it works: one Action on one **COMBINE** NLA track keying the head control's quaternion, solved
per frame by shortest arc (no roll, so no flip) and measured on the **deform** bone that carries the
skull, not on the control. Two gated records, in degrees: `gaze_error` over the window against
`quality.gaze_error_max_deg` (2°), and `gaze_step`, the largest head turn per frame with the ramps
included, against `max_step_deg`.

| Situation | Answer |
| --- | --- |
| target further than `max_angle_deg` from the current gaze | `VALIDATION_FAILED` "turn the body first": never clamp, never raise the bound to force it |
| head already on target | `VALIDATION_FAILED` "nothing to adjust" |
| head snaps faster than `max_step_deg` (`apply`) | `VALIDATION_FAILED`, nothing published: lengthen `blend_frames` |
| head control not in quaternion mode, or no `head` role | `RIG_MAPPING_REQUIRED` |
| character asked to look at itself, unknown instance | `VALIDATION_FAILED` |

Limits to state: head only (eyes, neck share and torso are not driven), no close-up is rendered for
this tool, the Director panel does not offer it, and custom tools cannot narrow it yet.

### Custom tools: bounded, tested, or refused

When the user asks for "a tool that…", first ask whether a **narrowed `contact_lock`** answers it
(fewer effectors, smaller `max_correction_m`, shorter blend). If yes:

1. Write `tools/custom/<tool_id>/tool.json` (start from
   [custom-tool-example.json](../assets/custom-tool-example.json)): `tool_id`, `version`, `purpose`,
   `base_tool`, `supported_rigs`, `bounds` (`effectors`, `max_correction_m` ≤ 0.5,
   `blend_frames_max`), `known_limits` (at least one), `tests` (distinct names, at least one
   `expect: "pass"`; add `expect: "refuse"` cases the tool must decline). Unknown fields — a
   `script`, for instance — are rejected.
2. `tool.inspect` ([request](../assets/request-tool-inspect.json)): status `declared`, `registered`,
   `registration_stale`, or `unsupported` with the limitation in words. **`unsupported` is the
   answer to give the user**: an unimplemented `base_tool` ("make the gesture wider" →
   `scale_gesture`) or a rig without IK and semantic profile (`fluidblend.simple_biped/1`) cannot be
   tested or registered. Do not look for a workaround.
3. `tool.test` ([request](../assets/request-tool-test.json), target `shot_id`): runs every declared
   test in memory on the shot's current revision, each on a freshly opened scene, and saves nothing.
   It exits 0 even when tests fail — read `metrics.all_passed` and `tool-test.json`. A `refuse` test
   passes only on a `VALIDATION_FAILED` refusal by the tool, not on a missing rig mapping.
4. `tool.register` ([request](../assets/request-tool-register.json), `test_report_path`): refuses a
   report with a failed or missing test, a report whose evidence no longer matches the shot's
   revision, a `tool.json` changed since the test, and a version already registered (bump
   `version`). On success it writes `tools/custom/<tool_id>/registration.json`.
5. Use it: `adjustment.preview` / `adjustment.apply` with `custom_tool_id`. The engine enforces the
   registered bounds before any task exists — another effector or a larger `max_correction_m` is
   `VALIDATION_FAILED`; an omitted `max_correction_m` means the tool's bound, not the wider default.
   Editing `tool.json` after registration disables the tool until it is tested and registered again.

The tests need a shot that **shows the problem** (a sliding stance to fix, a step to decline). Never
relax a test, a bound in `config/quality.json` or an `expect` to obtain a registration.

### Everything else: stop

Typical requests **not** covered: "make this gesture wider", "slow down the anticipation only",
"add a slider to tune the gaze", any tool that needs a new algorithm.

1. **Stop.** Do not write a `bpy` script in `tools/custom/`, do not run it through a workaround, do
   not present it as a delivered tool.
2. **Offer what exists**: `contact_lock` for a sliding contact; `animation.retime` for the duration
   of a whole clip. Neither handles a partial segment, amplitude or gaze.
3. **Do not requalify the request.** "Slow down the anticipation only" is not `animation.retime`: the
   P0 retime stretches the entire clip. Say so instead of delivering a silent approximation.

## Tool contract

`contact_lock` declares it in `ADJUSTMENT_TOOLS` (`src/fluidblend/contracts/production.py`); a unit
test refuses an empty field or a declared test file that does not exist. Every tool declares,
without exception:

| Field | Content |
| --- | --- |
| identifier, version | stable, versioned |
| purpose | what the tool does, in one verifiable sentence |
| supported rigs | explicit profiles; outside the list = refusal, not degradation |
| parameters | bounds and units for each one |
| time scope | the `[start, end_exclusive)` window affected |
| affected channels | bones and properties touched, protected channels excluded |
| preconditions | required scene state |
| preview mode | how to see the effect without applying it |
| effects on sources | what is modified, what is copied |
| rollback method | how to return to the previous state |
| tests | unit tests and a Blender fixture |
| known limits | cases not handled, named |

Mandatory life cycle: targeted specification → code → unit tests → Blender fixture →
before/after preview → measurement → registration as a validated capability. A button wired to an
empty function is not a tool. An algorithm that only handles one case must be **named and documented
as such**.

Permanent prohibitions, including while developing a tool: modifying the security core
(`core/paths.py`, `core/permissions.py`, `core/locks.py`), relaxing a threshold in
`config/quality.json` to make a result pass, deleting or neutralizing an acceptance test.

## Planned adjustments (not available, except `contact_lock`)

| Tool | Function | Essential verification |
| --- | --- | --- |
| `retime_segment` | change the duration of a portion and move the associated events | order of keys and events preserved |
| `scale_gesture` | change the amplitude of allowed channels | rig limits and contacts preserved |
| `look_at_target` | set gaze target, influence and speed | no abrupt flip, no out-of-limit rotation |
| `contact_lock` | stabilize a hand or a foot over a given window | contact error measured in the right space |
| `root_path_adjust` | move the global trajectory | no double application of the translation |
| `loop_cleanup` | fix a loop seam | pose continuity and, if requested, velocity continuity |
| `curve_cleanup` | reduce noise or redundant keys | maximum deviation under threshold, contacts untouched |
| `expression_strength` | modulate an available expression | shape key bounds, combination with the lips |

`contact_lock` and `curve_cleanup` are explicitly **bounded** pieces of development, not universal
solvers. A stance lock must distinguish intentional stance, walking and deliberate sliding; if it
cannot, it must not be offered.

Implementations under consideration, leaning on native Blender rather than home-made code:
`graph.decimate` in `ERROR` mode, `graph.clean` and `graph.euler_filter` for curve cleanup; the
`CYCLES` F-modifier plus `pose.propagate(mode='LAST_KEY')` and a continuity measurement for looping;
bounded `TRACK_TO` or `DAMPED_TRACK` constraints then a bake for gaze; a windowed `COPY_LOCATION`
then `nla.bake(visual_keying=True, clear_constraints=True)` for contact.

## Blender panel (lot 3, not available)

A `Director` panel is planned inside Blender: target selection, parameters, interval, `Preview`,
`Apply`, `Revert`, status and a link to the report. The widgets would call **the same operations** as
the CLI, never a parallel logic.

Constraints already settled: bounded, responsive sliders that do not accumulate hundreds of
keyframes on every drag; preview on a variant or on a reversible temporary state; debounce through
`bpy.app.timers`, which restricts the panel to GUI mode since timers do not fire under
`--background`; a confirmation creates an explicit new revision.

A possible HTML/JS interface belongs to P2. If it ever happens: modern JavaScript, English variable
names, `let` rather than `var`, no `var`, no jQuery, no heavy framework for a simple panel.

## Related acceptance scenario

Scenario B08 ("ask for a missing tool on an unsupported rig" → a bounded tool with a test, or a clear
limitation, never a false success) passes: unimplemented base tool and IK-less rig get a stated
limitation and no registration, a tool failing its own test stays unregistered, a bounded tool is
tested, registered, applied within its bounds and refused beyond them. Faced with an out-of-scope
request, the only acceptable answer remains a clear statement of the limitation.
