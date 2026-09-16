# Sources: projects studied, licenses and references

An inventory of the open source projects and documentation consulted while designing the kit (source
pages verified on 16 September 2026). It serves as credit and as a starting point for the following
lots: nothing here is vendored unless stated otherwise, and the licenses listed are those observed
on that date — re-check them before reusing any code.

## Survey of prior art and what is taken from it

### 2.1 MCP and Blender agents

| Project | License | State | What is taken |
| --- | --- | --- | --- |
| [ahujasid/mcp-for-blender](https://github.com/ahujasid/mcp-for-blender) — PyPI `mcp-for-blender` 2.0.0 (16/09/2026), 28.7k ★ | MIT | TCP socket add-on on `localhost:9876` + stdio MCP server; 31 tools including `get_scene_info`, `get_object_info`, `get_viewport_screenshot`, `execute_blender_code`, `export_scene` (GLB/FBX); `mcp>=1.9,<2`; **refuses to start under `-b`**; unauthenticated socket; opt-out telemetry | **P0 live adapter**. Socket-side names ≠ MCP names (`execute_code` vs `execute_blender_code`) → always discover through `list_tools` |
| [lab/blender_mcp](https://projects.blender.org/lab/blender_mcp) — official Blender Lab project, v1.0.2 | GPL-3.0-or-later | Blender ≥ 5.1; `*_for_cli` tools that open a `.blend` in `--background`; `weak_sandbox.py`; not published on PyPI | Ideas only (CLI tools, weak sandbox); no vendored code (GPL) |
| [PatrykIti/blender-ai-mcp](https://github.com/PatrykIti/blender-ai-mcp) | Apache-2.0 | Typed operations (bounded macros, no free-form bpy), deterministic measurements and assertions (`scene_measure_gap`, `scene_assert_contact`, `scene_compare_snapshot`), machine-readable `guided_flow_state`, vision only after numeric confirmation; Blender 5.0 end to end | **Target architecture**: copy the measurement/assertion layer and the session state structure |
| [sandraschi/blender-mcp](https://github.com/sandraschi/blender-mcp) | MIT | Headless by default (`blender --background` as a subprocess), optional live bridge | Confirms the "headless batch + optional live" choice |
| [pakkio/mcp-blender](https://github.com/pakkio/mcp-blender) | MIT | `execute_batch` with snapshot-based rollback, `create/restore_scene_checkpoint` | Minimal checkpoint/rollback model |
| [halilogia/Blender-AI-Sidebar](https://github.com/halilogia/Blender-AI-Sidebar) | GPL-3.0 | Mutations with `bpy.ops.ed.undo_push()`, approval gates by risk, Blender 5.2 | Idea: risk classes per operation |
| [dcc-mcp/dcc-mcp-maya](https://github.com/dcc-mcp/dcc-mcp-maya) | MIT | `project_save` / `project_resume` (rehydration payload), `affinity: main`, `_safe_session` | Cross-session resumption model |
| [gd3kr/BlenderGPT](https://github.com/gd3kr/BlenderGPT) | MIT | Abandoned (2023); free-form Python code, unverified | Anti-pattern |

Cross-cutting finding (5 MCP projects grepped): **nobody implements idempotency, expected revision
or reconciliation after a timeout**. That is the kit's added value.

### 2.2 Headless pipelines and tooling

| Project | License | What is taken |
| --- | --- | --- |
| [DLR-RM/BlenderProc](https://github.com/DLR-RM/BlenderProc) 2.8 | GPL-3.0 | Launch pattern: `[blender, "--background", "--python-use-system-env", "--python-exit-code", "2", "--python", run.py, "--", args...]` (the idea, not the code) |
| [studio/blender-studio-tools](https://projects.blender.org/studio/blender-studio-tools) | GPL-3.0-or-later | `scripts/project-tools/`: declarative scaffold `folder_structure*.json`, `run_blender.py`, index `builder.blender.org/download/daily/?format=json&v=1`; extension manifest with `wheels = [...]` (the official route for pure dependencies inside Blender) |
| [studio/flamenco](https://projects.blender.org/studio/flamenco) `simple_blender_render.js` | GPL-3.0 | Render idempotency: `use_overwrite=False`, `use_placeholder=True`, `use_file_extension=True`; `--render-frame a..b` chunks; dependent `preview-video` task |
| [blender/blender-asset-tracer](https://projects.blender.org/blender/blender-asset-tracer) 2.2.0 | GPL-3.0-or-later | `pyproject.toml` template (`uv_build`, `[project.scripts]`, `[dependency-groups]`); a `.blend`'s dependencies through `bpy.data.file_path_map()` (5.1+) |
| [princeton-vl/infinigen](https://github.com/princeton-vl/infinigen) 2.0 | BSD-3 | uv structure + `uv.lock` + `.python-version`; task graph where the `.blend` of step N-1 is the checkpoint |
| [ynput/ayon-blender](https://github.com/ynput/ayon-blender) | Apache-2.0 | Injecting the runtime through `BLENDER_USER_SCRIPTS` / `PYTHONPATH` without installing an add-on |
| [mondeja/pytest-blender](https://github.com/mondeja/pytest-blender) 3.0.8 | BSD-3 | `blender_executable`, `blender_version`, `install_addons_from_dir` fixtures for `tests/blender/` |
| [astral-sh/uv](https://github.com/astral-sh/uv) 0.12.15 | Apache/MIT | `uv run`, `uv lock --check`, `--locked` in CI |
| [tox-dev/filelock](https://github.com/tox-dev/filelock) 3.32.7 | MIT | Cross-process locks (LockFileEx on Windows) |
| pydantic 2.13.5 / msgspec 0.21.1 / jsonschema 4.26 | MIT / BSD-3 / MIT | Contracts + schema generation |

### 2.3 Animation, rigging, lip-sync, mocap

| Project | License | What is taken |
| --- | --- | --- |
| Rigify (core add-on of Blender 5.2) | GPL (bundled) | P1 rig profile; `pose.rigify_generate` operator; `rigify.ik2fk`/`fk2ik`; "Rig Bake Settings" as a model for a range UI |
| [KBSBAUDRICE/Retarget](https://github.com/KBSBAUDRICE/Retarget) v5.2.0 (Expy-Kit + AnimAide fork, Blender ≥ 5.0) | GPL-3.0-or-later | Optional P1 adapter (external add-on); Mixamo/UE/Daz/MMD presets; "Extract Metarig" |
| [pKrime/Expy-Kit](https://github.com/pKrime/Expy-Kit) | GPL v3 | **Preset format**, name to name (`Rigify_Controls`, `Rigify_Deform`, `Mixamo`, `Unreal_Mannequin`), reimplemented as JSON in `animation/rig-maps/` |
| [Mwni/blender-animation-retargeting](https://github.com/Mwni/blender-animation-retargeting) 2.4 | GPL-3.0-or-later | Idea: an explicit rest-pose alignment step before baking |
| [Rokoko/rokoko-studio-live-blender](https://github.com/Rokoko/rokoko-studio-live-blender) 1.4.3 | LGPL-3.0 | Optional adapter; requires identical source and target poses |
| [DanielSWolf/rhubarb-lip-sync](https://github.com/DanielSWolf/rhubarb-lip-sync) 1.14.0 | MIT | External process; `mouthCues[{start,end,value}]` JSON; shapes A–F plus G, H, X |
| [Premik/blender_rhubarb_lipsync_ng](https://github.com/Premik/blender_rhubarb_lipsync_ng) 1.8.1 | MIT | cue → Action → NLA strip model (2 interleaved tracks), Action Slots 4.4+; reusable code (MIT) |
| Blender native | — | `graph.decimate`, `graph.clean`, `graph.euler_filter`, `pose.propagate(mode='LAST_KEY')`, Cycles F-modifier + Cycle-Aware Keying, `nla.bake`, Key ‣ Blend (Ease, Blend to Neighbor), Motion Paths |
| [squall01337/mixamo-llm-mocap](https://github.com/squall01337/mixamo-llm-mocap) | MIT | "Motions are data, not code": JSON specs, frame-by-frame QA reporting the diverging windows |
| [freemocap/freemocap](https://github.com/freemocap/freemocap) 2.0.0-alpha, [EricGuo5513/momask-codes](https://github.com/EricGuo5513/momask-codes) | AGPL-3.0 / MIT (weights undeclared) | P2/P3 only; MoMask is the only one to output BVH; HY-Motion requires 24–26 GB of VRAM (out of reach for a GTX 1080 Ti) |

### 2.4 Game, glTF, video, assets

| Project | License | What is taken |
| --- | --- | --- |
| [KhronosGroup/glTF-Validator](https://github.com/KhronosGroup/glTF-Validator) 2.0.0-dev.3.10 | Apache-2.0 | JSON report: `issues.numErrors`, `messages[].code/severity/pointer`, `info.hasSkins/animationCount/maxInfluences`; YAML `ignore:` configuration |
| [donmccurdy/glTF-Transform](https://github.com/donmccurdy/glTF-Transform) CLI 4.5.0 | MIT | `inspect --format csv` for statistics; **never** `draco`/`simplify` on a skinned GLB |
| Godot 4.7.2 (18/08/2026) | MIT | `--headless --path <p> --import` then `-s addons/gut/gut_cmdln.gd -gdir=res://test -gexit`; `AnimationTree` + `parameters/playback`.`travel("walk")`; `CharacterBody3D` |
| [bitwes/Gut](https://github.com/bitwes/Gut) 9.7.1 | MIT | Headless tests, exit 0/1 |
| [Jeh3no/Godot-Third-Person-Controller](https://github.com/Jeh3no/Godot-Third-Person-Controller) | MIT | Basis for `templates/game-godot/`: GDScript FSM + AnimationTree, "Godot 4.4–4.7 fully supported" |
| [Coding-Solo/godot-mcp](https://github.com/Coding-Solo/godot-mcp) | MIT | Optional in P2; `godot_operations.gd` parameterised in JSON |
| Three.js r186 (`three` 0.186.0) | MIT | `GLTFLoader` + `AnimationMixer.crossFadeTo`; official `webgl_animation_skinning_blending` example |
| FFmpeg 8.0.1 (installed) | GPL build | Recipes tested in §6.7 |
| Poly Haven API `api.polyhaven.com` | CC0 assets, no key required | `GET /assets?t=models`, `GET /files/<slug>` (URL + MD5) → a verifiable local cache; the official add-on is paid → do not use it |
| Quaternius Universal Animation Library, Kenney | CC0 | Redistributable fixtures (FBX/Blend; GLB conversion through Blender) |
| [Upliner/CharMorph](https://github.com/Upliner/CharMorph) "Vitruvian" base | GPL-3 code; CC0 asset | Local generation of a CC0 skinned **Rigify** human for the P1 fixture; external tool, versioned output |
| Blender Studio Snow/Rain/Ellie | CC-BY | Referenced, not versioned (custom rigs/CloudRig, 20–106 MB) |
| Mixamo | Adobe | Redistribution forbidden → never in the repository |
| [ubisoft/shotmanager](https://github.com/ubisoft/shotmanager) (dormant), [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) 0.18.1 | GPL-3 / Apache-2.0 | "Shot" data model; OTIO as the pivot format for P2 export |

### 2.5 Existing skills

| Project | License | Note |
| --- | --- | --- |
| [arjun988/blender-skills](https://github.com/arjun988/blender-skills) 193 ★ | MIT | 94 skills built on BlenderMCP; **already contains a skill named `blender-director`**; the `.claude/skills/` + `.cursor/skills/` + `.mcp.json` split is worth imitating |
| [gamedev-skills/awesome-gamedev-agent-skills](https://github.com/gamedev-skills/awesome-gamedev-agent-skills) | Apache-2.0 | Engine/task router worth imitating for `references/game.md` |
| [agentskills/agentskills](https://github.com/agentskills/agentskills) | — | Frontmatter spec (`name` = the folder name, `a-z0-9-`, ≤64; `description` ≤1024); `skills-ref validate` |

---


## Sources consulted (16/09/2026)

MCP / clients: https://github.com/ahujasid/mcp-for-blender · https://pypi.org/project/mcp-for-blender/ · https://projects.blender.org/lab/blender_mcp · https://www.blender.org/lab/mcp-server/ · https://github.com/PatrykIti/blender-ai-mcp · https://github.com/sandraschi/blender-mcp · https://github.com/pakkio/mcp-blender · https://github.com/halilogia/Blender-AI-Sidebar · https://github.com/dcc-mcp/dcc-mcp-maya · https://github.com/modelcontextprotocol/python-sdk · https://py.sdk.modelcontextprotocol.io/ · https://code.claude.com/docs/en/mcp · https://code.claude.com/docs/en/skills · https://learn.chatgpt.com/docs/extend/mcp?surface=cli · https://learn.chatgpt.com/docs/build-skills · https://agentskills.io/specification · https://code.visualstudio.com/docs/copilot/customization/mcp-servers · https://github.com/arjun988/blender-skills

Blender / pipeline: https://www.blender.org/download/lts/ · https://developer.blender.org/docs/release_notes/4.4/upgrading/slotted_actions/ · https://developer.blender.org/docs/release_notes/5.0/python_api/ · https://docs.blender.org/api/current/bpy_extras.anim_utils.html · https://docs.blender.org/manual/en/latest/advanced/command_line/arguments.html · https://docs.blender.org/api/current/info_gotchas_threading.html · https://docs.blender.org/api/current/bpy.ops.export_scene.html · https://github.com/KhronosGroup/glTF-Blender-IO · https://pypi.org/project/bpy/ · https://projects.blender.org/studio/blender-studio-tools · https://projects.blender.org/studio/flamenco · https://projects.blender.org/blender/blender-asset-tracer · https://github.com/DLR-RM/BlenderProc · https://github.com/princeton-vl/infinigen · https://github.com/ynput/ayon-blender · https://github.com/mondeja/pytest-blender · https://github.com/astral-sh/uv · https://github.com/tox-dev/filelock · https://pypi.org/project/pydantic/ · https://pypi.org/project/msgspec/

Animation: https://docs.blender.org/manual/en/5.2/addons/rigify/index.html · https://github.com/blender/blender/tree/main/scripts/addons_core/rigify · https://extensions.blender.org/add-ons/retarget/ · https://github.com/KBSBAUDRICE/Retarget · https://github.com/pKrime/Expy-Kit · https://github.com/Mwni/blender-animation-retargeting · https://github.com/Rokoko/rokoko-studio-live-blender · https://github.com/DanielSWolf/rhubarb-lip-sync · https://github.com/Premik/blender_rhubarb_lipsync_ng · https://docs.blender.org/api/current/bpy.ops.graph.html · https://docs.blender.org/api/current/bpy.ops.pose.html · https://docs.blender.org/api/current/bpy.ops.nla.html · https://github.com/aresdevo/animaide · https://github.com/Upliner/CharMorph · https://quaternius.com/packs/universalanimationlibrary.html · https://kenney.nl/support · https://studio.blender.org/characters/ · https://github.com/freemocap/freemocap · https://github.com/EricGuo5513/momask-codes · https://github.com/Tencent-Hunyuan/HY-Motion-1.0 · https://github.com/squall01337/mixamo-llm-mocap

Game / glTF / video / assets: https://github.com/KhronosGroup/glTF-Validator · https://github.com/donmccurdy/glTF-Transform · https://godotengine.org/download/windows/ · https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html · https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/index.html · https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html · https://github.com/bitwes/Gut · https://github.com/MikeSchulze/gdUnit4 · https://github.com/Jeh3no/Godot-Third-Person-Controller · https://github.com/Coding-Solo/godot-mcp · https://github.com/godotengine/godot-blender-exporter · https://threejs.org/examples/webgl_animation_skinning_blending.html · https://www.npmjs.com/package/three · https://ffmpeg.org/download.html · https://www.gyan.dev/ffmpeg/builds/ · https://api.polyhaven.com · https://github.com/Poly-Haven/polyhavenassets · https://ambientcg.com · https://github.com/ubisoft/shotmanager · https://github.com/AcademySoftwareFoundation/OpenTimelineIO

Agents and research: https://github.com/threedle/ll3m (non-commercial license) · https://arxiv.org/abs/2504.01786 (BlenderGym) · https://github.com/gaoypeng/3dcodebench · https://github.com/runopti/L3GO · https://github.com/calesthio/OpenMontage (AGPL) · https://github.com/IvanMurzak/Unity-MCP · https://github.com/CoplayDev/unity-mcp
