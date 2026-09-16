# P0 acceptance report - generated automatically

Generated on 2026-09-16 20:49 UTC by `pytest --acceptance-report`. Blender: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.

Statuses: `passed` = real test passed; `failed` = failure; `not_run` = missing dependency, not counted as validated.

| Scenario | Title | Status | Duration | Notes |
| --- | --- | --- | --- | --- |
| A01 | Initialize in a Windows path with spaces and accents | passed | 0.07 s |  |
| A02 | Re-run the initialization on the same project | passed | 0.12 s |  |
| A03 | Inspect the scene through the configured MCP | passed | 7.3 s | 31 tools advertised by BlenderMCP; get_scene_info read without mutation; GUI session started and stopped by the test (port 9876) |
| A04 | Build two simple articulated characters and one prop (240 frames at 24 fps) | passed | 6.73 s | 41 objects, 2 armatures of 18 bones, cyclic slotted Actions, file reopened by scene.inspect |
| A05 | Re-run the same operation after a lost response | passed | 6.3 s | idempotent replay (same task_id, a single v001); different parameters -> SCENE_CONFLICT exit 3 |
| A06 | Interrupt the worker after an output is created but before commit | passed | 10.34 s | worker killed after the outputs were written -> unknown state (exit 5); reconcile -> failed + partial effects; re-run with the same operation_id -> a single v002 |
| A07 | Manually modify a protected object between two operations | passed | 3.33 s | hash mismatch -> SCENE_CONFLICT (exit 3), file preserved; `revision accept` -> revision 2; stale expected_revision=1 -> conflict |
| A08 | Slow down an animation on a variant | passed | 7.91 s | 48 -> 57.6 frames (x1.2), contact markers 1/25 -> 1/30, source v001 untouched (hash), 6 before/after frames |
| A09 | Render then assemble the preview | passed | 17.93 s | 240/240 Workbench PNG in 10.801 s, MP4 24/1 yuv420p, ffprobe nb_read_frames=240, 10 s duration, shot.validate technical_pass |
| A10 | Export an animation as GLB | passed | 8.23 s | Khronos 2.0.0-dev.3.10: 0 error, 0 warning(s); consistent Blender re-import |
| A11 | Run without network after an approved preparation | passed | 3.76 s | worker launched with --offline-mode (Blender network disabled), no provider enabled, scene produced without any download |
| A12 | Supply an escaping path or a command as a parameter | passed | 0.02 s | ../ paths, external absolute path and UNC -> PERMISSION_REQUIRED (exit 2); ';' in an enum -> VALIDATION_FAILED (exit 4); no file created |
| A13 | Exhaust the budget or request an unavailable permission | passed | 0.05 s | inspect profile -> PERMISSION_REQUIRED (exit 2); 240 frames > budget 24 -> BUDGET_EXCEEDED (exit 6); journal request_blocked |
| L01 | Live: identity check and read-only inspection of the open scene | passed | 5.09 s | identity (project, file, revision, runtime, clean) verified through bpy.ops.fluidblend.identity; scene.inspect ran in the GUI session; report published |
| L02 | Live: isolated write (retime) publishes a new version and reloads the session | passed | 11.55 s | retime executed in the open session; v002 saved as a copy, published, revision 2; session reloaded on v002; v001 hash unchanged |
| L03 | Live: unsaved manual changes block the write and are preserved | passed | 26.63 s | dirty session → SCENE_CONFLICT (exit 3), nothing published, manual change kept; scene.checkpoint snapshots the unsaved scene (copy=True) |
| L04 | Live: wrong file open in the session is refused | passed | 20.7 s | session opened on an unrelated unsaved scene → identity mismatch → SCENE_CONFLICT, no task executed in Blender |
| L05 | Live: lost response leaves an unknown state that reconciliation resolves | passed | 22.27 s | call timeout → task unknown (exit 5); retry refused until reconcile; reconcile → failed (result found, not committed); retry succeeds on the clean session |
