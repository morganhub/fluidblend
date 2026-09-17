# fluidblend game template (Godot 4.7)

Original GDScript, MIT like the rest of the kit; no third-party add-on, no binary. `game.import_test`
copies this folder next to a GLB exported by `game.export` (as `assets/character.glb`), lets Godot
import it headless and checks what the engine wrote. `game.smoke_test` then plays `scenes/main.tscn`.

- `scripts/main.gd` builds the test scene in code: floor, wall, pickup, light, camera, player.
- `scripts/player.gd`: `CharacterBody3D` with two states, `idle` and `walk`. It plays the first
  animation whose name contains "walk" and makes it loop (glTF carries no loop flag). Arrow keys
  move, the accept key picks the prop up; tests use `simulated_input` / `simulated_interact`, the
  same code path.
- `scripts/pickup.gd`: an `Area3D` prop that reparents itself to the body that takes it.
- `test/smoke.gd`: headless smoke test in plain GDScript (no GUT):
  `godot --headless --path . -s res://test/smoke.gd -- --report smoke.json`, exit 0 only if its 13
  checks pass, and it always writes the report.

Open the folder in Godot 4.7 to play it by hand. It is a test bed, not a game: make your own project
and keep the character import and the smoke-test idea.