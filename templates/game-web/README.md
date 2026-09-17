# fluidblend web test bed (Three.js)

Browser counterpart of `templates/game-godot`: the kit's **test bed**, not your game. `game.import_test`
with `"template": "web"` copies this folder next to an exported GLB (`assets/character.glb`);
`game.smoke_test` opens it in a headless Chrome or Edge and reads its report.

- `index.html` — import map to the vendored Three.js r186 (`vendor/three`, MIT, pinned by hash in
  `vendor/VENDOR.json`). Nothing is loaded from a CDN: the page works offline.
- `src/main.js` — scene built in code: floor, wall, a prop to pick up, the character under a
  controllable body. Arrows move, Space picks up.
- `src/player.js` — two states (`idle`, `walk`); the first clip whose name contains "walk"; the
  baked clip's horizontal root travel is removed (the body moves instead) and reported.
- `test/smoke.js` — `?smoke=1`: 14 checks through real keyboard events and fixed 1/60 s steps, then
  the share of the frame the character covers, read back from the GPU. `?shot=1`: one deterministic
  frame for the evidence screenshot.

A browser refuses to load a GLB from `file://`: serve the folder
(`fluidblend preview web --project . --game-dir <published game folder>`).

Code style: ES modules, `let` only, no framework, no jQuery.
