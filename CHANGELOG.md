# Changelog

Format: one entry per released version. Dates are those of the development machine.
This project follows semantic versioning from 1.0.0 onwards; before that, the interface may change.

## 0.6.3 — 2026-09-22 — what the round trip with fluidunreal found

Found by running fluidunreal's four hand-off requests for real, in Blender, against a bundle
fluidblend 0.6.2 had just exported.

- **`animation.bake` refuses a baked skeleton.** Baking it again used to succeed: no clip strip was
  left to inherit from and no IK to make rigid, so the travelling walk came back declared in place
  and not looping. It now stops (`UNSUPPORTED_CAPABILITY`), as `animation.create` already did, and
  says the control rig stays in the work version before the bake.
- **The command handed to fluidunreal exists.** After an export, `next_safe_actions` said
  `fluidunreal run bundle.accept --source-path …`, a flag that kit never had. It now describes the
  `bundle.accept` request and gives the absolute path of the published folder, which is what that
  kit needs; `references/game.md` says the same.
- **Output is UTF-8 even when redirected.** Windows wrote the ANSI code page into a pipe, so an agent
  reading it as UTF-8 got `D�mo Studio` for `Démo Studio`, and copied a path that does not
  exist.
- Runtime and add-on move to 0.6.3: re-run `fluidblend runtime install --enable`. Nothing changes
  for fluidunreal: the bundle stays 1.1 and the reusable core is untouched.

## 0.6.2 — 2026-09-21 — the bundle names the range to bake, and grows without breaking readers

- **Breaking for fluidunreal: bundles are `schema_version` 1.1.** A reader pinned on fluidblend
  0.6.0 or 0.6.1 accepts `1.0` only and refuses them; move the pin to `v0.6.2` and refresh the
  vendored `schemas/handoff-bundle.json`. From 0.6.2 on, a reader reads any 1.x: strictly up to its
  own minor, and from a newer minor it drops the fields it does not know and names them in
  `warnings`. A minor only adds optional fields; a new major is refused.
- **`clips[].source_frame_range`**: the clip's range in Blender, beside `frame_range`, which is the
  GLB's and starts at 0 after `slide_to_zero`. A request sent back to this kit names the Blender
  one: fluidunreal's `bake_rigid_limbs` template built its `animation.bake` from the GLB range, and
  baked the walk fixture over frames 0–47 instead of 1–48.
- **`animation.bake` said `loop: false` whatever it baked.** It now declares a loop when every clip
  playing over the range loops. A declared loop or stride also needs each strip to play over the
  whole range a whole number of its cycles: frames outside a strip hold a pose, so a range that
  runs past the strip no longer passes as one stride. Otherwise neither is declared and a limit says
  why. The baked Rigify walk is `loop: true`; the library scenario's half cycle is not, and says so.
- **Reusable core**: `SCHEMA_VERSION`, `IDENT_PATTERN` and `BUNDLE_SCHEMA_VERSION`, which
  fluidunreal imports, are now part of the promise. The test also checks that every name the table
  promises exists in its module.
- Runtime and add-on move to 0.6.2: re-run `fluidblend runtime install --enable`.

## 0.6.1 — 2026-09-21 — a baked clip says what it does with the root

- **`animation.bake` declared every baked clip in place.** Its manifest carried no `root_motion`, so
  the default, `in_place`, reached `clip.json` and the hand-off bundle whatever the clip did. The
  Rigify walk baked for the Unreal preset travels its 0.6 m stride per loop; fluidunreal 0.3.1
  measured that on the imported bones and failed the declaration. The bake now inherits what the
  clips playing over its range declare: `root_motion`, `root_motion_channels`, and the stride when
  the range is a whole number of cycles of a single travelling clip (`repetitions` from two
  cycles). It names its `source_clip` when there is exactly one. It never guesses a stride: over a
  partial cycle, or from two travelling clips, none is declared and a limit says why.
- The Rigify scenario asserts the baked walk is `root_bone` with 0.6 m, in `clip.json` and in the
  bundle; the library scenario asserts two in-place clips bake to an in-place one.

## 0.6.0 — 2026-09-21 — hand-off to fluidunreal

Written so a sibling kit can drive another engine without copying this one. Nothing about the
existing targets changes; the 31 acceptance scenarios still pass, A10 and the Rigify scenario are
extended rather than altered.

- **`handoff-bundle.json`** (`contracts/handoff.py`, `schemas/handoff-bundle.json`): the transfer
  contract. Published beside the GLB on every successful `game.export`. Carries the producer, the
  axis convention, every file with its sha256, the licences copied in, the instances (asset id and
  version, licence, rig profile, skinned, baked, bone count, glTF node name, grips, reference pose)
  and the clips. Artifact `kind: "bundle"`, metrics `bundle`, `bundle_instances`, `bundle_clips`.
- **Clip ranges describe the GLB, not the scene**: with `slide_to_zero` the exported animation
  starts at frame 0, so that is the range the bundle reports. The Blender range stays in the clip
  index, where it belongs.
- **Reference pose**: the runtime records two to five deform bone heads at rest, in metres, so an
  engine-side kit measures the scale and the up axis it really got instead of assuming a conversion
  factor. `shot.build` stamps `fluidblend_asset_version` on the instance root.
- **`export_preset: "unreal"`** on `game.export`: validates, never repairs. Refuses an
  `animation_mode` other than `ACTIONS`, `slide_to_zero: false`, and a Rigify character without
  `export_def_bones`. An unbaked character is a warning; the bundle reports `baked: false`.
- **Licence rule**: an instance without a readable `license_path` stops the task under the preset
  (`PERMISSION_REQUIRED`, exit 2). Without the preset it is left out with a warning, and if no
  licence at all can be established no bundle is published: a bundle never redistributes an asset
  without its licence.
- **`targets.game_engine` accepts `"unreal"`**. On such a project, `game.import_test` without an
  explicit `template` is refused and points at the `fluidunreal` kit; `template: "web"` keeps the
  browser eyes. The project's `AGENTS.md` says the same.
- **Reusable core** (`docs/architecture.md`): 17 modules a sibling kit may import, with the promise
  that their API changes only with a CHANGELOG entry marked **breaking for fluidunreal**.
  `tests/unit/test_core_importable.py` proves each imports without pulling in `bpy`, a Blender
  adapter or `core.tasks`, and that the documented table cannot drift from the enforced list.
- Runtime and add-on move to 0.6.0 with the package: re-run `fluidblend runtime install --enable`.

## 0.5.1 — 2026-09-17 — game project scaffold

Found by installing the kit in a real game project: the assistant was handed a film shot with a
demonstration cast, and a `game_engine` field nothing read.

- `init --profile game` creates an empty work scene (`shot010` without the demonstration bipeds and
  lantern); `film` and `hybrid` are unchanged.
- `game.import_test` without `template` follows the project's `targets.game_engine` (`web` → Three.js,
  otherwise Godot) and reports where the choice came from. An explicit `template` still wins.
- The skill explains why a new project has a `shot010`, and to pass `--game-engine` at the first `init`.

## 0.5.0 — 2026-09-17 — web game target

The exported character in a browser: acceptance B09. 31 acceptance scenarios. Technical measurements
only: one rendered frame per run was looked at by the assistant, no human artistic validation.

- Add `templates/game-web/`: a Three.js r186 test bed (six files vendored, MIT, pinned by hash, no
  CDN), same gameplay as the Godot template, `let` only, no framework.
- `game.import_test` and `game.smoke_test` accept `template: "web"`: headless Edge or Chrome, offline,
  against a server on 127.0.0.1 for the run; 14 checks through keyboard events, then `web-frame.png`
  and `rendered_share` read back from the GPU — the first evidence of the skin drawn by a game engine.
  Root travel removed for the loop, model recentred and turned onto its travel direction, all reported.
- Add `fluidblend preview web` to play a published web game folder, the `game.browser` capability in
  `doctor`, and `browser_executable` in `config/local.json`. Godot stays the default template.

## 0.4.1 — 2026-09-17 — P1 refinement

Refinement of the P1 scope, no new domain. 154 tests pass on the reference machine. Technical
measurements only: no human artistic validation is recorded.

Upgrade note: run `fluidblend runtime install --enable` again and restart Blender.

- A skinned Rigify character now reaches Godot. `animation.bake` gains `rigid_limbs`: IK stretch is
  disabled in the export variant, because a compressed limb carries a non-uniform scale that neither
  baked keys nor glTF can represent (13.8 mm at the feet, refused with the offending bones named).
  The pose change (35.8 mm at the knees on the walk fixture) is reported, IK tips are gated at 1 mm.
- `animation.apply` re-measures the contacts of clips already applied, before and after, and refuses a
  clip that breaks one even though their channels are disjoint (`existing_clips` in the report).
- `adjustment.preview` renders close-ups of the contact over a fixed mark, before and after, so the
  correction can be seen and not only read (`review/closeup-before`, `review/closeup-after`).
- Fresh-agent test (an agent given only the skill took the Rigify character into Godot, same figures):
  the skill now ships an exact asset manifest example and states the path, licence and `shot.build`
  rules it had to learn from error messages; `game.export` no longer claims a skinned character is
  not skinned.
- Add a second adjustment tool, `look_at_target`: the head turns towards a point or an instance as a
  removable COMBINE layer, gated on gaze error (2°) and on head turn per frame; targets beyond
  `max_angle_deg` are refused. `adjustment.*` parameters now select the tool with `tool`; requests
  without it remain `contact_lock`. New quality key `gaze_error_max_deg`.
- Director panel: after a preview, the effector paths before (red) and after (green) and the anchor
  are drawn over the 3D view from the report's new `viewport` block. The session is not modified.
- `animation.bake` samples five frames instead of three, names the clip `<rig>.<output_clip>` and
  removes control-rig NLA tracks from the export variant (their Actions are kept).
- `game.export` counts deform bones when `export_def_bones` is set, exports only the baked clip of a
  baked skeleton, and replays the re-import: `skeleton_fidelity` gates deform bone heads at 1 mm.

## 0.4.0 — 2026-09-17 — production lot 4

Dialogue on a face, bounded retargeting and the Godot check: acceptance B02, B04 and B07. With them
every catalogue operation is available, each inside a narrow stated scope. 148 tests and 30
acceptance scenarios pass on the reference machine (A01–A13, B01–B08, L01–L09). Technical
measurements only: no human artistic validation is recorded. P2 stays on demand.

Upgrade note: run `fluidblend runtime install --enable` again and restart Blender. A
`rig-profile.json` mapped before this version lacks the four FK hand/foot roles needed by
`animation.retarget` and must be mapped again.

- Add the `vitruvian-face` fixture: the body fixture plus thirteen pinned CC0 facial morphs of the
  same upstream revision, as shape keys; `face_profile` on character manifests.
- Add `lipsync.apply` (Rhubarb cues → the character's real face controllers, fractional-frame
  timing, held cues gated on real mesh motion, mouth close-ups) and `expression.apply` — B04.
  Slotted-Action access now also serves shape-key datablocks.
- Add `animation.retarget` with one preset (`simple_biped_to_rigify`): rest-pose rotation deltas onto
  FK controls, test poses before the full range, limb directions gated on the deform chain, a
  motionless source refused, source Action untouched — B02. Four FK roles join the Rigify profile.
- Add `templates/game-godot/` (Godot 4.7, plain GDScript), `game.import_test` (headless import, checks
  what the engine wrote) and `game.smoke_test` (prototype launched, 13 checks, report required) — B07.
  GUT is not used. Every catalogue operation is now available, each within a stated narrow scope.
- Live and Director acceptance tests now check that the session answering on the MCP port is the
  one they opened, and declare themselves `not_run` otherwise (a user's Blender started in the same
  seconds could take the port).

## 0.3.0 — 2026-09-17 — production lot 3

Characters, clip library, measured contacts, prop hand-off, adjustments, custom tools, cooperative
live mode and the Director panel. 138 tests and 27 acceptance scenarios pass on the reference
machine (A01–A13, B01, B03, B05, B06, B08, L01–L09). Lot 4 — retargeting (B02), facial lip-sync
(B04), Godot import and smoke test (B07) — is not started and is planned for 0.4.0. Technical
measurements only: no human artistic validation is recorded.

Upgrade note: run `fluidblend runtime install --enable` again and restart Blender; the engine
refuses a runtime add-on whose version differs from the kit. A `rig-profile.json` mapped before this
version lacks the four deform-bone roles and must be mapped again before `walk`, `take_prop`,
`give_prop`, `contact_lock` or a hand-off.

- Correct unavailable preflight, uncertain cancellation, dependency-lock comparisons and
  source/revision-bound audit/preview evidence; disable automatic Blender scripts.
- Add bounded ZIP extraction, NTFS path checks, binary hash checks and fresh-clone LFS test.
- Add CC0 Vitruvian/Rigify fixture and tested local shot assembly, character inspection,
  semantic mapping and five-pose validation.
- Add bounded slotted Action library, NLA application, loop and measured deformation bake.
- Add shared contact/loop measurements and a root-motion `walk` recipe whose foot slide is gated at
  creation and re-measured by `animation.apply` on every repetition; `animation.loop` offsets
  root-motion channels and gates the evaluated seam pose. Rig profiles gain four deform-bone roles.
- Add prop assets (`kind: prop`, named grips), `shot.build` yaw placement, `take_prop` / `give_prop`
  palm-reach recipes and a bounded prop hand-off: revision-bound `interaction.plan`,
  `interaction.apply` with a world-transform-preserving `CHILD_OF` transfer, `interaction.validate`
  (contacts in the prop's space, hand-off jump, single authority, no constraint cycle) — B03.
- Add `adjustment.preview` / `apply` / `revert` with the `contact_lock` tool: a removable additive NLA
  layer, before/after measurements and frames, refusal of travel windows and planted contacts — B05.
- Add declarative custom tools (`tool.inspect` / `test` / `register`, `custom_tool_id` on adjustments):
  narrowing only, no code loaded, stated limitation for unsupported requests — B08.
- Make live execution cooperative (`start_request`, timer steps, `progress.json`) and believe
  `task cancel` only on the session's `cancel.ack.json` — L09.
- Add the Director panel: Preview / Apply / Revert of `contact_lock` run by the engine in a separate
  process, debounced sliders, session never keyed, identity-guarded reopen — B06. Clicked by a
  human before release, which led to: character list instead of a free field, wrapped messages,
  sidebar redraw after a timer, a stale-work-version guard with `Open latest version`, an
  unsaved-scene banner with `Reload file` (never "save"), plain-language results and a button to
  open the before/after frames.
- Add actual two-pass FFmpeg audio preparation and Rhubarb mouth-cue analysis.
- See `docs/production-p1.md` for exact scope, evidence and outstanding deliveries.

## 0.2.0 — 2026-09-16 — live mode

Writing into the Blender session the user has open, through the MCP add-on and an approved runtime
installed as a Blender add-on. Four operations are covered; everything else stays in batch mode.

### Added

- **Live mode** (`fluidblend run --mode live`): `scene.inspect`, `scene.audit`, `animation.retime`
  and `scene.checkpoint` run in the open Blender session instead of a dedicated headless process.
  Any other operation keeps running in batch even when `--mode live` is passed: it works on the
  published work version.
- **Runtime installed as a Blender add-on** — new module `src/fluidblend/core/runtime_install.py`,
  new commands `fluidblend runtime install [--enable] [--force]` and `fluidblend runtime status`.
  The runtime package is copied into
  `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\fluidblend_runtime\` with a
  `RUNTIME_MANIFEST.json` (version, tree hash, source, timestamp), then enabled headlessly in the
  Blender user preferences. `runtime status` exits 2 when the add-on is missing or out of date.
- **Runtime operators** (`blender_runtime/fluidblend_runtime/addon.py`, no UI, `bl_info` category
  `System`): `bpy.ops.fluidblend.identity()`,
  `bpy.ops.fluidblend.run_request(request_path=…, result_path=…)` and
  `bpy.ops.fluidblend.open_file(filepath=…)`. Those three calls are everything the engine ever
  transmits over MCP, so the add-on safe mode (`BLENDER_MCP_SAFE_MODE=1`) stays on.
- **Live adapter** (`src/fluidblend/adapters/blender_live.py`): one `uvx --python 3.11
  mcp-for-blender` stdio server per phase (identity, run, reload), using the `.mcp.json` entry named
  by `config/local.json` → `mcp.server_name`, or a generated entry when that file has none.
- **Identity check before every live operation**: runtime version equal to the kit version,
  `project_id` of the open scene equal to the project, open file equal to the shot's latest work
  version (real path comparison), and no unsaved change. Any mismatch is `SCENE_CONFLICT` (exit 3)
  and nothing is executed, so a human edit in progress is never lost.
- **`scene.checkpoint` in live mode**: snapshot of the open scene, unsaved work included, through
  `save_as_mainfile(copy=True)`; the copy is recorded under `checkpoints/` and the result carries a
  `was_dirty` metric. It is the only live operation that accepts a dirty session.
- **`blender-instance` lock**: a live task holds it in addition to the project lock.
- **`mode` field on task records** (`batch` or `live`) and two journal events,
  `live_identity_checked` and `live_session_reloaded`.
- **`fluidblend live status --project .`**: identity of the open session — file, project, shot,
  revision, dirty flag, runtime and Blender versions. Exit 2 when the session is unreachable.
- **`blender.runtime_addon` capability** in `fluidblend doctor`: `available`, `not_installed`, or
  `incompatible` when the installed hash differs from the kit's.

### Changed

- `animation.retime` in live mode saves the new version as a **copy** (`copy=True`); the engine
  publishes it as the next work version, records the new revision, then reloads the session on the
  published file (`bpy.ops.fluidblend.open_file`). The previous version on disk is untouched. If
  the reload fails, a warning asks the user to reopen the file manually before saving anything.
- A live call that exceeds `config/local.json` → `mcp.call_timeout_s` (60 s by default) leaves the
  task `unknown` (exit 5): the open scene may have been modified. A retry is refused until
  `fluidblend task reconcile` has settled the task, and the latest work version must be reopened in
  Blender before that retry.
- The runtime refuses `scene.build`, `shot.preview` and `game.export` inside a live envelope with
  `UNSUPPORTED_CAPABILITY`: they need a dedicated Blender process.
- Documentation: live mode rewritten in `README.md`, `docs/cli.md`, `docs/architecture.md`,
  `docs/security.md`, `docs/installation.md`, `docs/roadmap.md`, `docs/compatibility-matrix.md`,
  and in the skill (`SKILL.md`, `references/environment.md`, `references/recovery.md`,
  `references/project.md`).

### Verified

Acceptance L01 to L05 passed on the reference machine (Windows 11, Blender 5.2.2 LTS,
`mcp-for-blender` 2.0.0 with add-on 1.7), alongside A01 to A13: identity check and read-only
inspection of the open scene; isolated write publishing a new version and reloading the session,
with the previous version's hash unchanged; dirty session blocked with the manual change preserved,
and snapshotted by `scene.checkpoint`; unrelated file open in the session refused before anything
runs; lost response left `unknown`, then reconciled and re-run. Each scenario starts and stops its
own Blender GUI session and needs port 9876 free. Report:
`docs/acceptance-reports/latest-p0.md`.

## 0.1.1 — 2026-09-16 — stable release

Public release of the kit: documentation, code messages and skill entirely in English, external
tools supported, fixes found while running the full acceptance suite.

### Added

- **Full English documentation, code messages and skill.** `README.md`, `docs/`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, the human-readable CLI output and `skills/fluidblend/` are in English.
- **Support for approved external tools**, all `available` in `fluidblend doctor`: glTF-Validator
  2.0.0-dev.3.10 win64 (Apache-2.0) and Rhubarb Lip Sync 1.14.0 (MIT) in the user tools directory
  `%LOCALAPPDATA%\fluidblend\tools`, Godot 4.7.2 stable detection, and the MCP for Blender add-on
  (add-on 1.7, protocol 7, PyPI package `mcp-for-blender` 2.0.0) installed with
  `uvx --python 3.11 mcp-for-blender install-addon` then enabled in the Blender 5.2 preferences.
  Each tool is installed only on the user's explicit approval.
- **Tool discovery** — new module `src/fluidblend/adapters/tool_paths.py`: path from
  `config/local.json` → `PATH` → `%LOCALAPPDATA%\fluidblend\tools` (overridable with the
  `FLUIDBLEND_TOOLS_DIR` variable) → known Windows installers. For Godot the most recent version
  found is kept, preferring the `_console` variant. Details in `docs/installation.md` §3 bis.
- **`.mcp.json` at the root of the kit** (Claude Code project scope), generated by
  `fluidblend client-config --client claude`: `uvx --python 3.11 mcp-for-blender --host localhost
  --port 9876`, with `BLENDER_HOST`, `BLENDER_PORT`, `UV_PYTHON_PREFERENCE=only-managed`,
  `BLENDER_MCP_SAFE_MODE=1` and `DISABLE_TELEMETRY=true`. `fluidblend doctor` without `--project`
  now reads the `.mcp.json` of the current folder.
- **MCP client** (`adapters/mcp_client.py`): it reads each tool's `inputSchema` and synthesises the
  required string arguments — the real server requires `user_prompt` on almost every tool. The probe
  stays read-only: `list_tools` then `get_scene_info`.
- `providers.check` now runs through `fluidblend run` (host operation, read-only, no network).
- `scripts/demo.ps1`: end-to-end P0 demonstration on a fresh project.
- `CONTRIBUTING.md`.
- GitHub CI workflow (`.github/workflows/ci.yml`): lint, schema consistency and unit tests on
  Windows with `uv sync --locked`.

### Changed

- An out-of-scope path passed as an operation parameter now answers `PERMISSION_REQUIRED` (exit 2);
  injection into an enumeration value remains `VALIDATION_FAILED` (exit 4).
- `scene.checkpoint` is classified `write`: it takes the project lock and journals, without creating
  a prior checkpoint of its own — it *is* the snapshot.
- The scaffold creates the project's `requests/` folder; it is no longer a convention to be created
  by hand.
- `fluidblend doctor --project` writes the project's `dependencies.lock.json` (the manifest's
  `dependency_lock` path) in addition to the file passed to `--write-lock`.
- `dependencies.lock.json` no longer contains any machine path: versions, hashes, provenance and
  status only.
- The project skeleton now ignores `state/diagnostics/` and `state/resume-report.json`
  (machine-specific data).
- Internal design documents removed from the repository (specification, Lot 0 proposal, machine
  diagnostic); the public synthesis of the projects studied and of their licenses is in
  `docs/sources.md`.

### Fixed

- `game.export`: the exported object set is deduplicated (a held prop is both an instance and the
  child of a character), and the control re-import disables the glTF importer's bone shapes
  (`disable_bone_shape=True`), which added two `Icosphere` meshes and skewed the comparison.

### Verified

Acceptance A01 to A13 all passed on the reference machine (Blender 5.2.2 LTS, Windows 11), with no
`not_run`.

## 0.1.0 — 2026-09-16 — P0 foundation

First usable version: graftable skill, Python engine, headless Blender runtime.

### Added

**Skill** — `skills/fluidblend/SKILL.md` with agentskills.io frontmatter (`name`, `description`,
`license`, `compatibility`, `metadata`), twelve decision rules, a "request → mode → reference" table,
triggering use cases, invariants, mandatory stops and exit codes. Nine references loaded per mode in
`references/`, five copy-ready example requests in `assets/`, PowerShell wrapper
`scripts/fluidblend.ps1`.

**Engine** — `fluidblend` CLI with the subcommands `doctor`, `init`, `inspect`, `plan`, `run`,
`task` (`list`, `status`, `cancel`, `reconcile`), `validate`, `resume`, `revision`
(`list`, `accept`), `ops`, `schema` (`export`, `check`), `client-config`, `capabilities`. Pydantic
contracts exported as JSON Schema 2020-12 in `schemas/`. Append-only JSONL journal, compact
reconstructed state, idempotency registry, hash-based revisions, verified checkpoints, project lock,
budgets estimated before execution and calibrated on real measurements, path protection.

**Blender runtime** — `blender_runtime/fluidblend_runtime`, stdlib and `bpy` only. F-curves are
accessed exclusively through the slotted Actions API, with a guard test forbidding the legacy API
removed in Blender 5.0.

**Available operations (19)** — `environment.doctor`, `capabilities.list`, `providers.check`,
`project.init`, `project.inspect`, `project.plan`, `project.resume`, `scene.inspect`, `scene.audit`,
`scene.build`, `scene.checkpoint`, `animation.retime`, `shot.preview`, `shot.validate`,
`film.assemble`, `game.export`, `task.status`, `task.cancel`, `task.reconcile`.

**Demo scene** — `two_characters_prop` preset: two original stylised bipeds (18-bone FK armature,
`fluidblend.simple_biped/1` profile, boxes parented to the bones), a prop held in the first
character's right hand, a floor, a 35 mm camera, a sun, a 48-frame walk cycle looped through an
F-modifier and root displacement, 240 frames at 24 fps. The file is reopened and audited before
publication.

**Production project** — idempotent scaffold (`film`, `game`, `hybrid` profiles), `project.json`,
`config/local.json`, `config/permissions.json`, `config/quality.json`, `config/providers.json`
manifests, demo shot plan `shots/shot010/shot.json`, `AGENTS.md` and `CLAUDE.md`.

**Scripts** — `scripts/bootstrap.ps1` (sync, diagnostic, schemas, tests, installation suggestions
without automatic execution) and `scripts/install-skill.ps1` (local graft of the skill into a
project, never a global installation).

**Documentation** — `README.md`, `docs/installation.md`, `docs/architecture.md`, `docs/cli.md`,
`docs/compatibility-matrix.md`, `docs/security.md`, `docs/roadmap.md` and this changelog.

### Verified

P0 acceptance run on Blender 5.2.2 LTS under Windows 11: **A01 to A13 passed, no `not_run`**
(71 tests). The timestamped report is authoritative; regenerate it with
`uv run pytest tests --acceptance-report docs/acceptance-reports/latest-p0`.

Notable measurements: a 240-frame scene at 24 fps built, reopened and audited (two 18-bone
armatures, cyclic slotted Actions); retime from 48 to 57.6 frames with `duration_scale = 1.2`,
contact markers tracked and source Action untouched; 240 Workbench frames rendered then assembled
into a 24/1 `yuv420p` MP4, `nb_read_frames = 240` confirmed by ffprobe (240 Workbench frames in
≈10.8 s); worker interrupted before commit reconciled with no loss of source and no duplicated
version.

- **A03 passed**: the test itself launches an ephemeral **GUI** Blender session (a window visible
  for about ten seconds), waits for the `localhost:9876` socket, writes the `.mcp.json` of the
  temporary project, probes the server through `uvx mcp-for-blender` — 31 tools advertised by
  "BlenderMCP", `get_scene_info` read without mutation — then stops the single process it created.
  If port 9876 is already in use, the scenario is explicitly declared `not_run` rather than worked
  around.
- **A10 passed**: glTF-Validator 2.0.0-dev.3.10 reports 0 errors and 0 warnings on
  `shot010-characters.glb`, with a consistent Blender re-import.

### Not verified in this version

- **Live writing through MCP not tested**: only scene reading is exercised (A03). Scene identity,
  instance locks and isolated writing belong to lot 2.
- **`game` profile not tested**: Godot 4.7.2 is detected, but the kit provides neither a template
  nor an engine import. No playable prototype.
- **Lip-sync unavailable**: Rhubarb 1.14.0 is detected, but the `lipsync.*` operations are not
  implemented (lot 4).
- `fluidblend doctor --live` stays `unverified` as long as no GUI Blender session with the add-on is
  running: this is the expected behaviour, the batch CLI does not need live mode.
- Systems other than Windows 11, and Blender series other than 5.2: not tested.

### Not implemented

Every operation of lots P1 and P2 is declared `available=false` and answers
`UNSUPPORTED_CAPABILITY` with exit code 2, without side effects: `character.*`, `rig.*`,
`animation.create`, `animation.apply`, `animation.loop`, `animation.retarget`, `animation.bake`,
`interaction.*`, `audio.*`, `lipsync.*`, `expression.*`, `adjustment.*`, `shot.build`,
`game.import_test`, `game.smoke_test`, `tool.*`.

None of these operations is simulated, worked around or replaced by an ad hoc script. Roadmap and
preparatory decisions: `docs/roadmap.md`.

### Constraints imposed by this version

- Blender of the **5.2** series is required; any other series is refused by the runtime.
- Synchronous batch execution: `bpy.app.timers` never fires under `--background`.
- The demo characters are not skinned (bone parenting), and have neither face nor fingers.
- `schema_version` is frozen at `1.0`; any change will require an explicit migration.
