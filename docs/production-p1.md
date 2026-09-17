# Unreleased P1 implementation status

This is an incremental implementation of the seven-delivery plan. It is not completion of the
whole TODO. P2 remains conditional on a real request. Existing P0 projects remain readable.
The catalogue contains 29 available operations (19 P0, 10 P1) and 14 unavailable P1 operations.
The historical 6–9 / 4–6 day estimates have not been revalidated against the remaining work.

| Delivery | Implemented and automatically exercised | Remaining |
| --- | --- | --- |
| Foundation | Unavailable-operation preflight, uncertain cancellation, locked diagnostics, binary hash checks, revision/source-bound evidence, bounded ZIP extraction helper, disabled automatic Blender scripts, disposable fresh-clone LFS test | Public archive import workflow; cooperative live cancellation; full dependency migration regression |
| Character | Pinned CC0 Vitruvian, Rigify 0.6.10 fixture, local append `shot.build`, inspect/map/five-pose validation (B01) | Versioned rest-pose/scale/hierarchy migrations, links and overrides |
| Animation | `create/apply/loop/bake`; idle, turn, look-at, reach, react; Action slots, NLA ownership, seed and stage metadata, versioned clip indexes | Walk, take/give, full stage workflow, anatomical limits, support-relative contact measurements |
| Interaction/adjustment | Contracts remain unavailable | B03/B05/B08 and complete tool lifecycle |
| Live/Director | Four operations, monotonic edit generation and guarded publication/reload; unconfirmed cancellation stays unknown | Cooperative tasks, Director panel, B06 |
| Film/dialogue | Two-pass FFmpeg normalization, 48 kHz PCM, rational sample/frame durations, real Rhubarb phonetic analysis | Face controllers/application, sequences, human review workflow, final render, B04 |
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
`stage` and optional `profile_path`; supported presets are `idle_neutral`, `turn`, `look_at`,
`reach`, `react`. Clip creation creates a library Action without assigning it. `animation.apply`
takes `clip_id` and `start_frame`; channel overlap with active animation is refused.
`animation.loop` takes target `clip_id`, `output_clip`, `repetitions`; it checks endpoint curve
values, not foot contact or velocity continuity. `animation.bake` takes `output_clip`,
`frame_range`, `step`; it produces an export variant with constraints/drivers removed. The control
rig source is preserved. A mesh comparison at start/middle/end must stay within 1 mm; this is
a sampled check, not an all-frame proof. The baked variant cannot accept control-rig recipes.

Indexes in `animation/clips/<id>/clip.json` cite the immutable work blend and report with hashes.
Contacts/events are declared but initially empty. Missing locomotion/contact features must not
be presented as measured. Current NLA conflict resolution is conservative refusal, not blending.

## Audio workflow

`audio.prepare` reads a project-relative `source_path`, including `audio/source/`, without changing
it. Optional bounded loudness parameters are in its schema. It publishes a mono PCM16 48 kHz WAV
and `audio-preparation.json`. `lipsync.analyze` takes `source_path` and publishes Rhubarb A–H/X cues.
The source hash is checked before/after. Analysis does not apply keys or approve speech/voices.

## Evidence and qualification

See `docs/acceptance-reports/implementation.md` for the combined regression and the earlier
`production-p1.md`, `consolidation-batch.md` reports. B01 uses the actual 37,436-vertex skinned fixture; animation and audio
integration tests use real Blender, FFmpeg and Rhubarb. B02–B08 are not declared passed.
Technical automation, assistant visual inspection and human artistic approval are separate.
Five inspected deformation views and their hashes are in `docs/reviews/vitruvian/review.json`.
The squat is a deformation test with floating feet; it is not a contact test.
No human approval or fresh Claude Code/Codex skill session is recorded for this change.

Validation on 17 September 2026: combined regression **121 passed** in 324.35 s, including
A01–A13, B01, L01–L08. Subsequent targeted checks passed: **98 unit tests**, **3 audio integration
tests** (mono, stereo, dependency absence), and strengthened B01 with duplicate-instance refusal
and additive shot assembly (**1 passed**, 28.49 s). Lint, formatting, schema consistency and skill
format validation pass. Ten new copy-ready request examples are validated against their contracts.
The live tests use their own GUI process and install the runtime into the existing approved add-on
location. Long calls are still synchronous; cancellation acknowledgement and Director remain pending.
