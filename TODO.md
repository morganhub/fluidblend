# TODO — what remains to complete the specification

Reference: the "Blender Director" specification v1.0 (16 September 2026, kept outside this public
repository) and [docs/roadmap.md](docs/roadmap.md). Status on 16 September 2026, version 0.2.0.

Legend: `[x]` done and proven by tests · `[ ]` not started · `[~]` partial. Every item becomes
`available: true` in the catalogue only with real Blender tests and an acceptance scenario; until
then it answers `UNSUPPORTED_CAPABILITY`.

## Done

- [x] Lot 0 — diagnosis, sourced decisions (`docs/sources.md`), locked Blender 5.2.2 LTS.
- [x] Lot 1 — P0 foundation: project scaffold, contracts, journal/revisions/locks/checkpoints,
      batch runtime (`scene.build`, `scene.inspect`, `scene.audit`, `animation.retime`,
      `shot.preview`, `game.export`), `shot.validate`, `film.assemble`, `providers.check`,
      acceptance A01–A13 (`docs/acceptance-reports/latest-p0.md`).
- [x] Lot 2 — live mode: runtime as an approved Blender add-on, identity check, isolated writes,
      instance lock, lost-response reconciliation, acceptance L01–L05.
- [x] Delivery: English skill + docs, CI (unit tests on Windows), `scripts/demo.ps1`, external tools
      discovery (`%LOCALAPPDATA%\fluidblend\tools`), sanitized dependency lock.

## Lot 3 — characters, animation library, adjustments (P1)

Spec §9, §10, §11, §12, §16.1, §18 (lot 3); acceptance B01, B03, B05, B06, B08. Estimate: 6–9 days.

### Rigs and characters (§9)
- [ ] `rig.map`: semantic rig profile (`root`, `pelvis`, `head`, `left_hand_ik`, `right_foot_ik`…)
      independent of bone names; declare absent controls and what their absence prevents.
      First profile: Rigify 0.6.10 (`torso`, `hand_ik.L`, `foot_ik.L`, switches on `*_parent.L`).
- [ ] `rig.validate` / `character.inspect`: test poses (arms up, bent elbow, bent knee, squat,
      torso twist), uninfluenced vertices, missing bones, problematic scales, deformation views.
- [ ] Skinned reference character fixture with a full rig profile and a recorded license
      (candidate: CharMorph "Vitruvian" CC0 + Rigify; never Mixamo) → `fixtures/`, `licenses/`.
- [ ] Rest-pose / rig-scale / hierarchy fixes treated as migrations with regression tests.
- [ ] Never apply transforms blindly on skinned or animated characters (guard + test).

### Animation library and layers (§10)
- [ ] Clip manifests (`animation/clips/<clip_id>/`: Action + slot, rig profile, timing, loop,
      root-motion convention, contacts, events, owned channels) and `animation/recipes/`.
- [ ] Initial library on the Rigify profile: `idle_neutral`, `walk`, `turn`, `look_at`, `reach`,
      `take_prop`, `give_prop`, `react` — each with supported rigs and parameters.
- [ ] `animation.create`, `animation.apply`, `animation.loop`, `animation.bake`.
- [ ] Logical layers (global motion, locomotion, upper body, hands/contacts, gaze, face, lips,
      secondary) mapped to NLA tracks and channel partitions; documented priority resolution;
      double-transform detection.
- [ ] Blocking → spline → polish workflow support; never convert dense mocap to constant
      interpolation by default.
- [ ] Procedural motion (§10.5): recorded seeds, amplitude ranges, anatomical limits (camera
      paths, secondary oscillation, blinks, extras variation).

### Interactions (§11)
- [ ] `interaction.plan` / `interaction.apply` / `interaction.validate`: choreography manifest
      (participants, prop instance, interval, anchors, contact windows, ownership order).
- [ ] Prop hand-off: attach with known offset → synchronized reach → constraint transfer keeping
      the world transform → release; validations for position jump, hand distance, ownership → B03.
- [ ] Single authority on a prop's transform; no constraint cycles between characters.
- [ ] Timing change propagates to contacts, gaze, events and associated audio; report breaks.

### Adjustment tools (§12)
- [ ] Tool contract (§12.2): id, version, purpose, supported rigs, bounded parameters with units,
      time scope, affected channels, preconditions, preview mode, effects on sources, revert,
      tests, known limits. Lifecycle spec → code → unit tests → Blender fixture → before/after
      preview → measurement → registered capability.
- [ ] `adjustment.preview` / `adjustment.apply` / `adjustment.revert`.
- [ ] Tools (§12.3): `retime_segment` (keys and events order preserved), `scale_gesture`
      (rig limits, contacts preserved), `look_at_target` (no flips, limits), `contact_lock`
      (measured contact error in the right space) → B05, `root_path_adjust` (no double
      application), `loop_cleanup` (pose and optional velocity continuity), `curve_cleanup`
      (max deviation under threshold, contacts untouched), `expression_strength`.
- [ ] `tools/custom/<tool_id>/` registry with `tool.inspect` / `tool.test` / `tool.register`;
      a bounded tool with tests or a clear limitation, never a fake success → B08.
- [ ] Quality measures (§16.1): foot slide ≤ 0.02 m, hand/prop contact ≤ 0.02 m, loop error,
      with the measurement defined (space, support window, sampling, control points, tolerance).

### Native Blender panel (§12.4)
- [ ] `blender_addon/`: "Director" panel — target, parameters, range, Preview / Apply / Revert,
      state, link to the report; same operations as the CLI/live mode; bounded, debounced sliders;
      preview on a reversible temporary state; Apply = explicit new revision → B06.

## Lot 4 — voice and game target (P1)

Spec §13, §14, §17 (B02, B04, B07), §18 (lot 4). Estimate: 4–6 days.

### Film, audio and rendering (§13)
- [ ] Film → sequence → shot organisation; `shot.build` assembling a shot from versioned assets
      (linked or appended, overrides inspected rather than applied blindly).
- [ ] Dialogue pipeline: approved text and voices, `audio.prepare` (FFmpeg `loudnorm` two-pass,
      always `aresample=48000`), exact audio/frame mapping, source track never overwritten.
- [ ] `lipsync.analyze` (Rhubarb 1.14, `-f json -r phonetic`) and `lipsync.apply` (cues A–H + X
      mapped to the rig's real face controllers, rest mouth, transitions, manual correction),
      `expression.apply` → B04.
- [ ] Animatic; blocking key frames and full-sequence preview; dense samples around contacts
      and transitions; before/after for every important fix; `technical_pass` →
      `visual_review_pending` → `art_approved` workflow with human decisions recorded in `reviews/`.
- [ ] Final render: image sequences with fixed resolution, frame rate, colour management,
      exposure, seed and engine settings; test an excerpt before a long sequence; simulation
      caches versioned by input hashes.

### Retargeting (§10.4)
- [ ] `animation.retarget` (bounded): preserve the source, identify source/target profiles,
      normalize conventions, verified reference pose, produce a new Action, test a few poses and
      a short excerpt first; record contacts and constraints → B02.
- [ ] Optional adapters as external add-ons (Retarget/Expy-Kit presets, Rokoko) — never vendored.

### Game (§14)
- [ ] Export contract: deform-skeleton variant, baked clips, compatible textures/materials,
      documented events, collision and LOD per target; recorded axes, units, root name, in-place
      vs root motion, loops, exported bones, influence limits, texture sizes, geometry budget.
- [ ] `templates/game-godot/` (Godot 4.7.2): test scene, controllable character, movement, at
      least two animation states, simple collision, one prop interaction (GDScript).
- [ ] `game.import_test` (headless `--import`, `.import` files verified) and `game.smoke_test`
      (GUT, exit 0/1) → B07; performance measured on a declared machine; if the engine is
      missing the game stays `not_tested`.
- [ ] `templates/game-web/` (Three.js r186, `let` only, no jQuery) only if the target is a web game.

## Lot 5 — studio extensions (P2, only on real demand)

Spec §1 (P2), §7.3, §10.5, §11, §12.4, §13, §18 (lot 5).

- [ ] Multi-shot render queue (task graph with chunks, no-overwrite frames, per-shot preview job).
- [ ] Cached simulations invalidated by geometry/timing/physics changes.
- [ ] Extras / crowd: phase offsets, speeds, trajectories with budgets.
- [ ] Optional providers with full declaration (§3.2): FreeMoCap, MoMask/BVH, motion catalogues,
      voice generators — source, version, code and weight licenses, data rights, network, account,
      cost, VRAM, formats, import/export test.
- [ ] Business MCP facade `fluidblend` over stable operations (stdio, typed parameters, central
      permissions, journal; logs on stderr; no public listener) (§7.3).
- [ ] Optional HTML/JS panel (modern JavaScript, no framework imposed) (§12.4).
- [ ] OpenTimelineIO export of the film timeline.

## Cross-cutting gaps against the specification

- [~] Live mode covers four operations only; client-owned MCP writes are not supported: the AI
      client must call `fluidblend run --mode live`. Shared operation ids and lock policy between
      shell and MCP tools remain to be exposed (§7.2).
- [ ] Human undo/edit signal in live sessions (`undo_post` handlers): identity is a snapshot,
      not a subscription (§7.4).
- [ ] Progress and cancellation of long live calls; `task.cancel` for live tasks (§7.5).
- [ ] Permissions enforced outside the agent's reach when the client allows it (hooks or client
      permission settings); the JSON permissions file remains a weak boundary (§15.3).
- [ ] Archive imports: size and expansion limits, external references of imported `.blend`
      files inspected before enabling scripts/drivers (§15.3) — partial (missing-file check only).
- [ ] Dependency migration policy: no component update mid-production without a migration branch
      and a regression run (§3.3); `dependencies.lock.json` compared against the runtime probe.
- [ ] Git LFS strategy for project binaries documented and verified end to end (§4.2).
- [ ] "Agent using the skill" tests (§17): a fresh session with only the skill, a test project and
      a realistic request; check reference selection, scope, no re-initialization, correct stops.
- [ ] Codex end-to-end check of the grafted skill (`.agents/skills/`) — only Claude Code exercised.
- [ ] Final delivery report distinguishing designed / implemented / automatically tested /
      visually inspected / user-validated (§19); record visual inspections and user decisions in
      `reviews/` (only automated tests are recorded today).
- [ ] Compatibility matrix upkeep: any Blender version other than 5.2.x announced only after a
      dedicated test run (§19).

## Not planned (out of scope by design)

- Direct calls to model APIs inside the engine, paid services, cloud asset transfers (§1.2).
- Universal retargeting between arbitrary rigs, "video generation as animation" (§1.3).
- Linux/macOS support: the specification targets a native Windows 11 workstation.
