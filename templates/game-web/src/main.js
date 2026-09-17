// Test scene built in code: a floor, a wall to collide with, a prop to pick up, and the exported
// character under a controllable body. The character is `assets/character.glb` (fluidblend game.export).
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { Player } from "./player.js";
import { runSmoke, renderedShare } from "../test/smoke.js";

export let WALL_X = 2.0;
export let PICKUP = new THREE.Vector3(-1.5, 0.5, 0);
export let REACH = 1.0;
let BACKGROUND = new THREE.Color(0x1a1a1f);

function box(name, at, size, color) {
  let mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), new THREE.MeshStandardMaterial({ color }));
  mesh.name = name;
  mesh.position.set(...at);
  return mesh;
}

export class Game {
  constructor(canvas) {
    this.canvas = canvas;
    this.scene = new THREE.Scene();
    this.scene.background = BACKGROUND;
    this.input = new Set();
    this.set = [
      box("Floor", [0, -0.1, 0], [20, 0.2, 20], 0x3a3d45),
      box("Wall", [WALL_X, 1.0, 0], [0.2, 2.0, 4.0], 0x8a6d4a),
    ];
    this.pickup = box("Pickup", PICKUP.toArray(), [0.12, 0.6, 0.12], 0xe0b040);
    this.scene.add(...this.set, this.pickup);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x30323a, 1.2));
    let sun = new THREE.DirectionalLight(0xffffff, 2.0);
    sun.position.set(3, 6, 4);
    this.scene.add(sun);
    this.camera = new THREE.PerspectiveCamera(45, 16 / 9, 0.1, 100);
    this.camera.position.set(0, 2.2, 6.0);
    this.camera.lookAt(0, 0.9, 0);
    this.renderer = null;
    try {
      // preserveDrawingBuffer: the smoke test reads the rendered pixels back.
      this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
    } catch (error) {
      this.webglError = String(error);
    }
    // Same path for a player and for the test: real keyboard events on the window.
    window.addEventListener("keydown", (event) => this.key(event, true));
    window.addEventListener("keyup", (event) => this.key(event, false));
  }

  key(event, down) {
    if (down) this.input.add(event.code);
    else this.input.delete(event.code);
    if (down && (event.code === "Space" || event.code === "Enter")) this.interact();
  }

  async load(url) {
    let gltf = await new GLTFLoader().loadAsync(url);
    this.clips = gltf.animations;
    this.player = new Player(gltf.scene, gltf.animations);
    this.scene.add(this.player.group);
  }

  nearbyPickup() {
    let dx = this.player.group.position.x - PICKUP.x;
    let dz = this.player.group.position.z - PICKUP.z;
    return this.pickup.parent === this.scene && Math.hypot(dx, dz) < REACH;
  }

  interact() {
    if (this.player && !this.player.held && this.nearbyPickup()) this.player.hold(this.pickup);
  }

  step(dt) {
    this.player.update(dt, this.input, WALL_X - 0.1);
  }

  resize() {
    let width = this.canvas.clientWidth || 960;
    let height = this.canvas.clientHeight || 540;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    if (this.renderer) this.renderer.setSize(width, height, false);
  }

  render() {
    if (this.renderer) this.renderer.render(this.scene, this.camera);
  }
}

async function main() {
  let hud = document.getElementById("hud");
  let game = new Game(document.getElementById("view"));
  let query = new URLSearchParams(location.search);
  let report = { engine: "three.js r" + THREE.REVISION, webgl: game.renderer !== null, loaded: false };
  try {
    await game.load("./assets/character.glb");
    report.loaded = true;
  } catch (error) {
    report.error = String(error);
  }
  game.resize();
  if (query.has("smoke")) {
    if (report.loaded) Object.assign(report, runSmoke(game, THREE));
    else Object.assign(report, { passed: false, checks: [{ name: "main_scene_loads", passed: false }] });
    report.rendered_share = report.loaded ? renderedShare(game) : null;
    // The host reads this element from the dumped DOM: no report, no proof.
    document.getElementById("fluidblend-report").textContent = JSON.stringify(report);
    document.title = "fluidblend-smoke-done";
    hud.textContent = report.passed ? "smoke test passed" : "smoke test FAILED";
    return;
  }
  if (!report.loaded) {
    hud.textContent = "character.glb did not load: " + report.error;
    return;
  }
  if (query.has("shot")) {
    // One deterministic frame for the evidence screenshot: mid-stride, facing the camera's side.
    game.input.add("ArrowRight");
    for (let i = 0; i < 30; i++) game.step(1 / 60);
    game.player.group.position.set(0, 0, 0);
    // Close enough to judge the skin: the play camera shows the whole test bed instead.
    game.camera.position.set(1.6, 1.3, 3.0);
    game.camera.lookAt(0, 0.9, 0);
    hud.innerHTML = "<b>" + game.player.walkName + "</b> · " + report.engine;
    game.render();
    document.title = "fluidblend-shot-done";
    return;
  }
  hud.innerHTML =
    "Arrows: move · Space: pick up the prop · clip <b>" + (game.player.walkName || "none") + "</b> · " + report.engine;
  window.addEventListener("resize", () => game.resize());
  let clock = new THREE.Clock();
  function frame() {
    game.step(Math.min(clock.getDelta(), 0.05));
    game.render();
    requestAnimationFrame(frame);
  }
  frame();
}

main();
