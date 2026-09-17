# Three.js r186 — MIT

Copyright © 2010-2026 three.js authors. Licence text: `templates/game-web/vendor/three/LICENSE`
(copied unchanged from the package).

Source: https://registry.npmjs.org/three/-/three-0.186.0.tgz
(tarball SHA-256 `61eeff9d7616005c9a481c796f52287d81fbbbc0d55eaca5565322924252c1aa`).

Six files are vendored unchanged into `templates/game-web/vendor/three/` so that the web test bed
works offline: `three.module.js`, `three.core.js`, `addons/loaders/GLTFLoader.js`,
`addons/utils/BufferGeometryUtils.js`, `addons/utils/SkeletonUtils.js` and `LICENSE`. Their hashes
are pinned in `templates/game-web/vendor/VENDOR.json`; a unit test checks them, and
`game.smoke_test` refuses a game folder whose engine files differ.
