# fluidblend acceptance report - generated automatically

Generated on 2026-09-17 13:18 UTC by `pytest --acceptance-report`. Blender: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.

Statuses: `passed` = real test passed; `failed` = failure; `not_run` = missing dependency, not counted as validated.

| Scenario | Title | Status | Duration | Notes |
| --- | --- | --- | --- | --- |
| A01 | Initialize in a Windows path with spaces and accents | passed | 0.07 s |  |
| A02 | Re-run the initialization on the same project | passed | 0.11 s |  |
| A03 | Inspect the scene through the configured MCP | passed | 7.08 s | 31 tools advertised by BlenderMCP; get_scene_info read without mutation; GUI session started and stopped by the test (port 9876) |
| A04 | Build two simple articulated characters and one prop (240 frames at 24 fps) | passed | 6.01 s | 41 objects, 2 armatures of 18 bones, cyclic slotted Actions, file reopened by scene.inspect |
| A05 | Re-run the same operation after a lost response | passed | 5.96 s | idempotent replay (same task_id, a single v001); different parameters -> SCENE_CONFLICT exit 3 |
| A06 | Interrupt the worker after an output is created but before commit | passed | 10.57 s | worker killed after the outputs were written -> unknown state (exit 5); reconcile -> failed + partial effects; re-run with the same operation_id -> a single v002 |
| A07 | Manually modify a protected object between two operations | passed | 3.61 s | hash mismatch -> SCENE_CONFLICT (exit 3), file preserved; `revision accept` -> revision 2; stale expected_revision=1 -> conflict |
| A08 | Slow down an animation on a variant | passed | 8.0 s | 48 -> 57.6 frames (x1.2), contact markers 1/25 -> 1/30, source v001 untouched (hash), 6 before/after frames |
| A09 | Render then assemble the preview | passed | 18.38 s | 240/240 Workbench PNG in 10.555 s, MP4 24/1 yuv420p, ffprobe nb_read_frames=240, 10 s duration, shot.validate technical_pass |
| A10 | Export an animation as GLB | passed | 8.85 s | Khronos 2.0.0-dev.3.10: 0 error, 0 warning(s); consistent Blender re-import |
| A11 | Run without network after an approved preparation | passed | 3.13 s | worker launched with --offline-mode (Blender network disabled), no provider enabled, scene produced without any download |
| A12 | Supply an escaping path or a command as a parameter | passed | 0.02 s | ../ paths, external absolute path and UNC -> PERMISSION_REQUIRED (exit 2); ';' in an enum -> VALIDATION_FAILED (exit 4); no file created |
| A13 | Exhaust the budget or request an unavailable permission | passed | 0.05 s | inspect profile -> PERMISSION_REQUIRED (exit 2); 240 frames > budget 24 -> BUDGET_EXCEEDED (exit 6); journal request_blocked |
| B01 | Versioned skinned Rigify character: semantic mapping and five deformation poses | passed | 26.81 s | Vitruvian CC0, 37,436 influenced vertices, complete Rigify mapping; five finite deformation responses and PNG views; source hash unchanged; incomplete mapping refused; artistic review pending |
| B03 | Prop hand-off between two characters: contacts, jump and ownership measured | passed | 34.45 s | baton passed hero-01 -> sidekick-01 at frame 40; receiver contact 0.01 mm in prop space, jump 0.000 mm; unreachable target, stale plan and second authority refused; a 6 cm human move is detected by validate and preserved; artistic review pending |
| B04 | Dialogue line: audio prepared, cues analysed, mouth keyed on the real face | passed | 14.54 s | offline Windows voice -> two-pass normalization -> Rhubarb 42 cues -> 10 held cues checked on shape keys (B, C, F, X), mouth up to 10.5 mm; fractional frames, source audio untouched; recognition, text, voice and performance are not approved; artistic review pending |
| B05 | Sliding stance fixed with contact_lock: preview, apply, revert | passed | 44.63 s | artist drift 100.0 mm -> 0.06 mm after contact_lock (world, DEF-foot.L); travel window and planted foot refused; preview saved nothing; revert restored the drift exactly; artist file hash unchanged; artistic review pending |
| B06 | Director panel: Preview / Apply / Revert run the engine, the session stays clean | passed | 62.17 s | panel preview 100.0 -> 0.06 mm with the session untouched (same edit generation, not dirty); five slider moves -> one debounced preview; Apply and Revert published new revisions through the engine journal and reopened the session; Apply refused on unsaved changes, artist object preserved; driven through the panel operators, no human clicked the UI |
| B08 | Custom tool request: a bounded tested tool, or a stated limitation | passed | 27.49 s | unimplemented base tool and IK-less rig -> stated limitation, no test, no registration; failing tool not registered; bounded declarative tool tested (1 fix, 1 refusal), registered, applied within its bounds, refused beyond them and after its declaration changed; no custom code is executed |
| L01 | Live: identity check and read-only inspection of the open scene | passed | 5.71 s | identity (project, file, revision, runtime, clean) verified through bpy.ops.fluidblend.identity; scene.inspect ran in the GUI session; report published |
| L02 | Live: isolated write (retime) publishes a new version and reloads the session | passed | 8.79 s | retime executed in the open session; v002 saved as a copy, published, revision 2; session reloaded on v002; v001 hash unchanged |
| L03 | Live: unsaved manual changes block the write and are preserved | passed | 10.38 s | dirty session → SCENE_CONFLICT (exit 3), nothing published, manual change kept; scene.checkpoint snapshots the unsaved scene (copy=True) |
| L04 | Live: wrong file open in the session is refused | passed | 10.82 s | session opened on an unrelated unsaved scene → identity mismatch → SCENE_CONFLICT, no task executed in Blender |
| L05 | Live: lost response leaves an unknown state that reconciliation resolves | passed | 20.52 s | call timeout → task unknown (exit 5); retry refused until reconcile; reconcile → failed (result found, not committed); retry succeeds on the clean session |
| L06 | Live: edit between admission and execution is preserved | passed | 5.45 s |  |
| L07 | Live: edit before publication prevents publishing or reloading | passed | 7.0 s |  |
| L08 | Live: guarded reload preserves a later edit; undo generation is monotonic | passed | 10.57 s |  |
| L09 | Live: progress is reported and a cancellation is acknowledged by the session | passed | 8.63 s | cancel requested after 2 step(s); session wrote cancel.ack.json, task cancelled, nothing saved, session clean and reusable; without acknowledgement the state stays unknown (unit test) |
