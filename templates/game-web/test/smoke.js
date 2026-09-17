// Smoke test of the prototype, run by `?smoke=1`. It drives the game through real keyboard events
// and fixed 1/60 s steps, so the result does not depend on the machine's frame rate.
let DT = 1 / 60;

function press(code, down) {
  window.dispatchEvent(new KeyboardEvent(down ? "keydown" : "keyup", { code }));
}

function bonePositions(game, THREE) {
  // Relative to the body: the body's own travel must not count as "the clip moves the bones".
  let origin = game.player.group.position;
  let out = [];
  game.player.model.updateMatrixWorld(true);
  game.player.model.traverse((node) => {
    if (node.isBone || node.isMesh) out.push(node.getWorldPosition(new THREE.Vector3()).sub(origin));
  });
  return out;
}

export function runSmoke(game, THREE) {
  let checks = [];
  let check = (name, passed, value) => checks.push({ name, passed: Boolean(passed), value: value ?? "" });
  let player = game.player;
  let steps = (count) => {
    for (let i = 0; i < count; i++) game.step(DT);
  };

  check("main_scene_loads", game.scene.getObjectByName("Floor") && game.scene.getObjectByName("Wall"));
  check("character_model_instantiated", player.model && player.model.children.length > 0);
  check("animation_player_found", player.mixer !== null && game.clips.length > 0, game.clips.length);
  check("walk_animation_found", player.walk !== null, player.walkName);
  steps(10);
  check("stands_on_floor", Math.abs(player.group.position.y) < 1e-6, player.group.position.y);
  check("idle_state_plays_nothing", player.state === "idle" && !(player.walk && player.walk.isRunning()));

  let start = player.group.position.x;
  press("ArrowRight", true);
  steps(5);
  check("walk_state_plays_walk_clip", player.state === "walk" && player.walk && player.walk.isRunning());
  // A clip can "run" and move nothing (wrong bone names, empty tracks): measure the skeleton itself.
  let before = bonePositions(game, THREE);
  steps(12);
  let after = bonePositions(game, THREE);
  let moved = Math.max(0, ...before.map((p, i) => p.distanceTo(after[i])));
  check("walk_clip_moves_bones", moved > 0.01, moved);
  steps(240);
  press("ArrowRight", false);
  let limit = 2.0 - 0.1 - 0.3;
  check("character_moved", player.group.position.x - start > 1.0, player.group.position.x - start);
  check("wall_stops_character", Math.abs(player.group.position.x - limit) < 1e-6, [player.group.position.x, limit]);
  steps(5);
  check("back_to_idle", player.state === "idle" && !(player.walk && player.walk.isRunning()));

  press("ArrowLeft", true);
  for (let i = 0; i < 600 && !game.nearbyPickup(); i++) game.step(DT);
  press("ArrowLeft", false);
  steps(2);
  check("reached_pickup", game.nearbyPickup(), player.group.position.x);
  press("Space", true);
  press("Space", false);
  steps(2);
  check("prop_is_held", player.held !== null && player.held.parent === player.group);
  check("pickup_is_empty", game.scene.children.indexOf(game.pickup) === -1);

  return {
    passed: checks.every((c) => c.passed),
    checks,
    clip: player.walkName,
    clips: game.clips.map((c) => c.name),
    root_motion_removed_m: player.rootMotionRemoved,
    recentered_m: player.centerOffset,
    skinned_meshes: countSkinned(player.model),
  };
}

function countSkinned(model) {
  let count = 0;
  model.traverse((node) => {
    if (node.isSkinnedMesh) count++;
  });
  return count;
}

// Share of the frame covered by the character alone, read back from the GPU: the only evidence
// that the skin is really drawn by the engine. `null` when the browser gave no WebGL context.
export function renderedShare(game) {
  if (!game.renderer) return null;
  let hidden = [...game.set, game.pickup];
  for (let object of hidden) object.visible = false;
  game.player.group.position.set(0, 0, 0);
  game.camera.position.set(1.6, 1.3, 3.0);
  game.camera.lookAt(0, 0.9, 0);
  game.render();
  let gl = game.renderer.getContext();
  let width = gl.drawingBufferWidth;
  let height = gl.drawingBufferHeight;
  let pixels = new Uint8Array(width * height * 4);
  gl.readPixels(0, 0, width, height, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
  let background = [pixels[0], pixels[1], pixels[2]];
  let covered = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    let delta =
      Math.abs(pixels[i] - background[0]) + Math.abs(pixels[i + 1] - background[1]) + Math.abs(pixels[i + 2] - background[2]);
    if (delta > 24) covered++;
  }
  for (let object of hidden) object.visible = true;
  return covered / (width * height);
}
