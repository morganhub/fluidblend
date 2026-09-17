# Vitruvian body fixture — CC0-1.0

Authors: Sean Buckley and Olaf Delgado-Friedrichs; additional contributors are credited in
the upstream `config.yaml`. Source revision: `c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44`.

License declaration: https://github.com/Upliner/CharMorph-Vitruvian/blob/c252d1fc7f00ba59d87b66b3d32fa3471fc6ee44/config.yaml
The declaration identifies the asset as `Vitruvian (CC0)` and `license: CC0`.
License text: https://creativecommons.org/publicdomain/zero/1.0/legalcode

Only `char.blend`, the `metarig` object from `rigs.blend`, and `weights/rigify.npz` are used.
No Mixamo object, motion or weights are imported. No CharMorph or Rigify source code is vendored.
Rigify is executed from the locked Blender installation to produce the derived rig.
Embedded text blocks, textures and particle hair are removed from the resulting neutral body fixture.
Input and output hashes are recorded in `fixtures/vitruvian/asset.json`.

Reproduce with `scripts/generate_vitruvian_fixture.py` inside Blender 5.2.2. Set
`FLUIDBLEND_FIXTURE_CACHE` to a directory containing the three hash-checked inputs; the weights
file must be named `weights-rigify.npz`. The generator refuses to overwrite an existing fixture.
Deformation review is separate from license verification and automated skin checks.
