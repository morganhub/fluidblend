# Baton test prop

- **Asset**: `baton`, a 0.35 m cylinder used as the hand-off prop of acceptance scenario B03.
- **Origin**: original geometry created by `scripts/generate_prop_fixture.py` from a Blender
  primitive; no third-party data, texture or code.
- **License**: CC0-1.0 (public domain dedication).
- **Distribution**: not versioned as a binary. The tests generate it on demand with the locked
  Blender, hash it and write its `asset.json` (kind `prop`, `root_object`, `grips`) into the
  temporary project.
- **Grips** (prop local space, metres): `primary` `[0, 0, 0]` (object origin), `secondary`
  `[0, 0, 0.15]`.
