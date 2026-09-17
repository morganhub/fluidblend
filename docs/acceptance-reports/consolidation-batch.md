# P0 acceptance report - generated automatically

Generated on 2026-09-17 08:51 UTC by `pytest --acceptance-report`. Blender: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.

Statuses: `passed` = real test passed; `failed` = failure; `not_run` = missing dependency, not counted as validated.

| Scenario | Title | Status | Duration | Notes |
| --- | --- | --- | --- | --- |
| A04 | Build two simple articulated characters and one prop (240 frames at 24 fps) | passed | 6.36 s | 41 objects, 2 armatures of 18 bones, cyclic slotted Actions, file reopened by scene.inspect |
| A05 | Re-run the same operation after a lost response | passed | 6.51 s | idempotent replay (same task_id, a single v001); different parameters -> SCENE_CONFLICT exit 3 |
| A06 | Interrupt the worker after an output is created but before commit | passed | 10.48 s | worker killed after the outputs were written -> unknown state (exit 5); reconcile -> failed + partial effects; re-run with the same operation_id -> a single v002 |
| A07 | Manually modify a protected object between two operations | passed | 3.53 s | hash mismatch -> SCENE_CONFLICT (exit 3), file preserved; `revision accept` -> revision 2; stale expected_revision=1 -> conflict |
| A08 | Slow down an animation on a variant | passed | 8.01 s | 48 -> 57.6 frames (x1.2), contact markers 1/25 -> 1/30, source v001 untouched (hash), 6 before/after frames |
| A09 | Render then assemble the preview | passed | 19.48 s | 240/240 Workbench PNG in 11.206 s, MP4 24/1 yuv420p, ffprobe nb_read_frames=240, 10 s duration, shot.validate technical_pass |
| A10 | Export an animation as GLB | passed | 10.56 s | Khronos 2.0.0-dev.3.10: 0 error, 0 warning(s); consistent Blender re-import |
| A11 | Run without network after an approved preparation | passed | 3.48 s | worker launched with --offline-mode (Blender network disabled), no provider enabled, scene produced without any download |
