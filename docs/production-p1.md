# P1 implementation status — 0.3.0

Version 0.3.0 delivers lot 3 of the seven-delivery plan. It is not completion of the whole TODO:
lot 4 is in progress on `main` for 0.4.0 — B04 facial lip-sync is done, B02 retargeting and B07 Godot
are not started. P2 remains conditional on a real request. Existing P0 projects remain readable.
The catalogue contains 40 available operations (19 P0, 21 P1) and 3 unavailable P1 operations.
The historical 6–9 / 4–6 day estimates have not been revalidated against the remaining work.

| Delivery | Implemented and automatically exercised | Remaining |
| --- | --- | --- |
| Foundation | Unavailable-operation preflight, uncertain cancellation, locked diagnostics, binary hash checks, revision/source-bound evidence, bounded ZIP extraction helper, disabled automatic Blender scripts, disposable fresh-clone LFS test | Public archive import workflow; full dependency migration regression |
| Character | Pinned CC0 Vitruvian, Rigify 0.6.10 fixture, local append `shot.build`, inspect/map/five-pose validation (B01) | Versioned rest-pose/scale/hierarchy migrations, links and overrides |
| Animation | `create/apply/loop/bake`; idle, walk, turn, look-at, reach, take/give prop, react; Action slots, NLA ownership, seed and stage metadata, versioned clip indexes; shared foot-slide/contact/loop measurements, root-motion loop and apply | Full stage workflow, anatomical limits, arm swing and heel roll, finger poses |
| Interaction/adjustment | Prop assets (`kind: prop`, grips); `interaction.plan/apply/validate` for one bounded prop hand-off: revision-bound plan, `CHILD_OF` transfer preserving the world transform, contacts measured in the prop's space, jump, single-authority and cycle checks (B03); `adjustment.preview/apply/revert` with one tool, `contact_lock`, as a removable additive NLA layer with a declared tool contract (B05); declarative custom tools through `tool.inspect/test/register`, code-free, narrowing only (B08) | Timing propagation between participants, other interaction kinds; the seven other adjustment tools |
| Live/Director | Four operations, monotonic edit generation and guarded publication/reload; cooperative timer-driven execution with progress and acknowledged cancellation (L09); Director panel running `adjustment.*` through the engine with debounced sliders (B06) | Multi-step live operations (today a stop lands between operations' single step), live mode for more operations, in-viewport preview (the panel shows figures and before/after frames; a human clicked it on 17 September 2026 and five usability defects were fixed) |
| Film/dialogue | Two-pass FFmpeg normalization, 48 kHz PCM, rational sample/frame durations, real Rhubarb phonetic analysis; after 0.3.0: `vitruvian-face` fixture, `lipsync.apply` and `expression.apply` on shape keys with fractional-frame timing and real-motion gates (B04) | Short cues are passed through unchecked, no co-articulation, audio not in the sequencer, sequences, human review workflow, final render |
| Retarget/game | Existing GLB export only | Bounded retarget, Godot template/import/GUT, B02/B07 |

## Character workflow

The fixture is `fixtures/vitruvian/character.blend`; provenance, hashes and reproducible preparation
are in `licenses/vitruvian.md`. CharMorph code stays external. Copy the fixture into a project asset
version with a strict `schemas/asset.json` manifest (project-relative blend and license paths).
The acceptance helper in `tests/acceptance/test_characters.py` is a complete example.

Run `shot.build` with `assets: [{manifest_path, instance_id, location}]`, then `character.inspect`
on the instance, `rig.map` with the published `inspection_path`, and `rig.validate` with the
published `profile_path`. Inspection evidence must match the current scene revision/hash.
Incomplete controls are explicit and dependent operations refuse. No transform is applied to skin.
Adding assets to an existing shot preserves its contents, camera and timing. An existing instance
id is a conflict; `shot.build` never implicitly resets the shot or replaces a character.
Pose tests check finite responsive deformation and weights; they do not prove anatomy or contacts.

## Clip workflow

`animation.create` accepts `preset`, `output_clip`, `frame_range`, `amplitude` (0–0.6), `seed`,
`stage` and optional `profile_path`; supported presets are `idle_neutral`, `walk`, `turn`, `look_at`,
`reach`, `take_prop`, `give_prop`, `react` (the two hand recipes take `hand` plus `prop_instance_id`
or `target_point`). Clip creation creates a library Action without assigning it. `animation.apply`
takes `clip_id` and `start_frame`; channel overlap with active animation is refused.
`animation.loop` takes target `clip_id`, `output_clip`, `repetitions`; it checks endpoint curve
values, not foot contact or velocity continuity. `animation.bake` takes `output_clip`,
`frame_range`, `step`; it produces an export variant with constraints/drivers removed. The control
rig source is preserved. A mesh comparison at start/middle/end must stay within 1 mm; this is
a sampled check, not an all-frame proof. The baked variant cannot accept control-rig recipes.

Indexes in `animation/clips/<id>/clip.json` cite the immutable work blend and report with hashes.
Only `walk` and `take_prop` declare contacts and events. Missing locomotion/contact features must not
be presented as measured. Current NLA conflict resolution is conservative refusal, not blending.

Shared measurements live in `blender_runtime/fluidblend_runtime/anim/measures.py`; each record
carries its space, support window, sampling step, control point (deform bone), tolerance and
`passed` (`null` when ungated). `walk` is a root-motion cycle on IK feet (stride = 2 x amplitude,
blocking refused). Foot slide is gated at creation, and again by `animation.apply` for every window
of every repetition in the assembled scene, together with root travel against the declared stride.
`animation.loop` offsets root-motion channels and gates the evaluated seam pose; seam velocity is
reported ungated. Measured on the fixture: slide 0.07 mm over six windows, travel 1.800 m for three
0.6 m cycles. Limits: flat static ground, ankle point, no heel roll or arm swing; moving supports
are implemented in the sampler but not yet exercised by a scenario.

## Prop hand-off workflow

A prop is an asset of `kind: "prop"` (`root_object`, `grips` in local metres, no armature); manifests
without `kind` remain characters. `shot.build` places instance roots with `location` and
`rotation_z` (radians). The `baton` test prop is original CC0 geometry generated on demand by
`scripts/generate_prop_fixture.py` (`licenses/baton.md`); no binary is versioned for it.

`interaction.plan` (host) writes a reviewable `interaction-plan.json` bound by `evidence.json` to the
current revision; it does not read the scene. `interaction.apply` refuses a plan from another
revision or edited after review (`SCENE_CONFLICT`), a prop that already has a parent, constraint or
animation, occupied hand channels, and a target beyond 95 % of the arm. It keys both palms with the
arm IK, attaches the primary grip to the giver's hand, aims the receiver at the secondary grip where
it really is, and switches two `CHILD_OF` constraints with constant influence keys, the second
inverse computed so the world transform is unchanged. `interaction.validate` re-runs the same
measurement code on the current scene and exits 0 with `technical_pass: false` when it fails.

Measured on the fixture (B03, 0.7 m apart, hand-off at frame 40 of 80): receiver palm to secondary
grip before owning the prop 0.005 mm, prop jump across the transfer 0.0003 mm, rotation jump 0.
Contacts of the hand that owns the prop are true by construction and say nothing about reach. A
6 cm human move of the receiver is reported by `validate` (0.060 m contact error and jump) and the
edited file is preserved. `take_prop` / `give_prop` reuse the same palm reach as library clips for a
static prop or a world point. Limits: stationary characters, rigid unit-scale prop, open hands, no
wrist orientation, no intersection test, no propagation of a participant's retiming.
Assistant visual inspection of frames 1–80: the transfer reads correctly, fingers stay open and the
carried baton ends close to the receiver's thigh; this is not an artistic approval.

## Adjustment workflow

`adjustment.preview` (read, nothing saved), `adjustment.apply` and `adjustment.revert` (new versions)
share one computation and currently expose one tool, `contact_lock`, whose twelve-field contract is
`ADJUSTMENT_TOOLS["contact_lock"]`. The tool holds one IK hand or foot on the position its control
point has at the first frame of a marked window, in the world or in a support instance's space. It
adds one Action on one additive NLA track and records itself in the scene; sources are never edited
and `revert` removes exactly that layer, or answers `SCENE_CONFLICT` if it was changed by hand.
It refuses a contact already within tolerance, a limb in FK, and a drift above `max_correction_m`
(a window that contains a step is travel, not a sliding stance).

Measured on the fixture (B05): an artist keys a 0.100 m sideways drift of the character during the
left stance of a walk; preview and apply bring `DEF-foot.L` to 0.06 mm in world space, revert
restores 0.1000 m exactly, the artist's file hash is unchanged, the preview publishes four
before/after frames and no version. Limits: translation only, one effector per adjustment, other
contacts not re-planted, preview frames use the shot camera as framed (feet near the frame edge on
the fixture shot). The support-space variant is implemented and not yet exercised by a scenario.

## Custom tool workflow

A custom tool is `tools/custom/<tool_id>/tool.json`: a strict declaration that narrows a built-in
tool (`bounds`), names its limits and carries its tests. No code is loaded from `tools/custom/`; an
unknown field such as `script` is rejected. `tool.inspect` answers `unsupported` with the reason
for an unimplemented base tool or a rig profile the base tool does not support — the stated
limitation B08 asks for. `tool.test` runs each declared test in memory on a freshly opened copy of
the shot's current revision and exits 0 with `all_passed: false` on failure. `tool.register` accepts
only a report whose evidence still matches the shot, whose `tool_sha256` matches the declaration and
whose tests all passed, then the engine installs `registration.json`. `adjustment.preview/apply`
with `custom_tool_id` enforce the registered bounds at preflight and refuse a declaration edited
after registration.

B08 on the fixture: `scale_gesture` and `fluidblend.simple_biped/1` declarations are reported
unsupported, not tested, not registered; a tool expecting to fix a whole walk cycle fails its test
and is refused; `gentle-foot-lock` (feet, 0.12 m) passes one fix and one refusal, registers, plants
the foot (0.100 m → 0.06 mm), and is refused for a hand, for 0.15 m, and after its bound was edited.
Limit: with a single built-in tool, a custom tool can only be a stricter `contact_lock`.

## Dialogue workflow (after 0.3.0)

`fixtures/vitruvian-face/` is the body fixture plus thirteen CC0 facial morphs of the same pinned
upstream revision, turned into shape keys by `scripts/generate_vitruvian_face_fixture.py` (hashes in
its `asset.json`; the Rigify face bones still carry no weights). A character manifest may declare
`face_profile`; `charmorph-l3/1` maps Rhubarb's A–H to eight visemes, X to rest, and five
expressions. `lipsync.apply` converts cue times to `start_frame + seconds x fps` without rounding,
merges repeated cues, keys one Action on the shape-key datablock through the slotted helper and
places it on its own NLA track; a character without a face profile is refused
(`RIG_MAPPING_REQUIRED`), a second lip-sync on the same channels too (`SCENE_CONFLICT`). The write
is gated per held cue: own shape reached, others ≤ 0.05, and the evaluated mesh moved by at least
1 mm x strength against the same frame with the mouth shapes at rest (rest must not move).

Measured (B04): an offline Windows voice line, normalized then analysed by Rhubarb into 42 cues;
10 are long enough to be held at the default two-frame transition and all pass (B 10.5 mm, C 6.4 mm,
F 4.9 mm, X 0); the other 32 are passed through and **not** checked. On handmade cues at 24 fps with
audio time 0 on frame 11, 0.5 s lands on frame 23.0 and the wide-open shape moves the mouth 23 mm.
The first version of this check reported 0 mm for every cue: a muted NLA track leaves its last values
in place, so "with" equalled "without"; the reference is now the same frame with the shapes reset.
The first close-ups framed the top of the skull; they now aim at the vertices the shapes move.
Assistant visual inspection of the close-ups: mouth shapes read correctly; not an approval of the
acting, the voice or the text.

## Audio workflow

`audio.prepare` reads a project-relative `source_path`, including `audio/source/`, without changing
it. Optional bounded loudness parameters are in its schema. It publishes a mono PCM16 48 kHz WAV
and `audio-preparation.json`. `lipsync.analyze` takes `source_path` and publishes Rhubarb A–H/X cues.
The source hash is checked before/after. Analysis does not apply keys or approve speech/voices.

## Evidence and qualification

See `docs/acceptance-reports/implementation.md` for the combined regression and the earlier
`production-p1.md`, `consolidation-batch.md` reports. B01 uses the actual 37,436-vertex skinned fixture; animation and audio
integration tests use real Blender, FFmpeg and Rhubarb. B03, B04, B05, B06 and B08 pass; B02 and B07 are not declared passed.
Technical automation, assistant visual inspection and human artistic approval are separate.
Five inspected deformation views and their hashes are in `docs/reviews/vitruvian/review.json`.
The squat is a deformation test with floating feet; it is not a contact test.
No human approval or fresh Claude Code/Codex skill session is recorded for this change.

Latest full regression on 17 September 2026, after walk, prop recipes, the hand-off and
`contact_lock`, custom tools, cooperative live and the Director panel: **146 passed** in 621.85 s (after B04),
28 scenarios passed (A01–A13, B01, B03, B04,
B05, B06, B08, L01–L09),
lint, formatting and schemas clean. Earlier the same day: combined regression **121 passed** in 324.35 s, including
A01–A13, B01, L01–L08. Subsequent targeted checks passed: **98 unit tests**, **3 audio integration
tests** (mono, stereo, dependency absence), and strengthened B01 with duplicate-instance refusal
and additive shot assembly (**1 passed**, 28.49 s). Lint, formatting, schema consistency and skill
format validation pass. Ten new copy-ready request examples are validated against their contracts.
The live tests use their own GUI process and install the runtime into the existing approved add-on
location. Long calls are still synchronous; cancellation acknowledgement and Director remain pending.
