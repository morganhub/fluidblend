# P0 acceptance report - generated automatically

Generated on 2026-09-17 09:32 UTC by `pytest --acceptance-report`. Blender: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`.

Statuses: `passed` = real test passed; `failed` = failure; `not_run` = missing dependency, not counted as validated.

| Scenario | Title | Status | Duration | Notes |
| --- | --- | --- | --- | --- |
| A01 | Initialize in a Windows path with spaces and accents | passed | 0.08 s |  |
| A02 | Re-run the initialization on the same project | passed | 0.1 s |  |
| A12 | Supply an escaping path or a command as a parameter | passed | 0.02 s | ../ paths, external absolute path and UNC -> PERMISSION_REQUIRED (exit 2); ';' in an enum -> VALIDATION_FAILED (exit 4); no file created |
| A13 | Exhaust the budget or request an unavailable permission | passed | 0.05 s | inspect profile -> PERMISSION_REQUIRED (exit 2); 240 frames > budget 24 -> BUDGET_EXCEEDED (exit 6); journal request_blocked |
| B01 | Versioned skinned Rigify character: semantic mapping and five deformation poses | passed | 15.17 s | Vitruvian CC0, 37,436 influenced vertices, complete Rigify mapping; five finite deformation responses and PNG views; source hash unchanged; incomplete mapping refused; artistic review pending |
