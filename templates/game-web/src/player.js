// Controllable character with two states, `idle` and `walk`. Arrow keys move it; the walk clip is
// the first animation whose name says "walk" (the kit names clips `<rig>.<clip>`).
import * as THREE from "three";

export let SPEED = 1.6;
export let RADIUS = 0.3;

// A baked walk carries its travel on the top bone: played in a loop it would snap back every
// cycle, while the game already moves the body. The horizontal drift is removed, and reported.
export function makeInPlace(clip) {
  let removed = 0;
  let heading = 0;
  for (let track of clip.tracks) {
    if (!track.name.endsWith(".position") || track.times.length < 2) continue;
    let last = track.values.length - 3;
    let dx = track.values[last] - track.values[0];
    let dz = track.values[last + 2] - track.values[2];
    let drift = Math.hypot(dx, dz);
    if (drift < 0.05) continue;
    let span = track.times[track.times.length - 1] - track.times[0];
    for (let i = 0; i < track.times.length; i++) {
      let t = (track.times[i] - track.times[0]) / span;
      track.values[i * 3] -= dx * t;
      track.values[i * 3 + 2] -= dz * t;
    }
    if (drift > removed) {
      removed = drift;
      // Where the clip travels is where the character faces: exports do not agree on a forward axis.
      heading = Math.atan2(dx, dz);
    }
  }
  return { removed, heading };
}

export class Player {
  constructor(model, clips) {
    this.group = new THREE.Group();
    this.group.name = "Player";
    this.model = model;
    this.state = "idle";
    this.held = null;
    this.mixer = null;
    this.walk = null;
    this.walkName = "";
    this.rootMotionRemoved = 0;
    this.centerOffset = 0;
    if (model) {
      this.group.add(model);
      this.mixer = new THREE.AnimationMixer(model);
      let clip = clips.find((c) => c.name.toLowerCase().includes("walk"));
      if (clip) {
        let travel = makeInPlace(clip);
        this.rootMotionRemoved = travel.removed;
        // The body turns towards +Z when it moves along +Z: bring the clip's own forward onto +Z.
        model.rotation.y = -travel.heading;
        this.walk = this.mixer.clipAction(clip);
        this.walkName = clip.name;
      }
      // A character exported from its place in a shot is not at the origin: put it under the body.
      let center = new THREE.Box3().setFromObject(model).getCenter(new THREE.Vector3());
      model.position.x -= center.x;
      model.position.z -= center.z;
      this.centerOffset = Math.hypot(center.x, center.z);
    }
  }

  // `limitX`: the wall face the body may not cross.
  update(dt, input, limitX) {
    let x = (input.has("ArrowRight") ? 1 : 0) - (input.has("ArrowLeft") ? 1 : 0);
    let z = (input.has("ArrowDown") ? 1 : 0) - (input.has("ArrowUp") ? 1 : 0);
    let length = Math.hypot(x, z);
    if (length > 0.1) {
      this.group.position.x = Math.min(this.group.position.x + (x / length) * SPEED * dt, limitX - RADIUS);
      this.group.position.z += (z / length) * SPEED * dt;
      // glTF characters face +Z.
      this.group.rotation.y = Math.atan2(x, z);
    }
    this.setState(length > 0.1 ? "walk" : "idle");
    if (this.mixer) this.mixer.update(dt);
  }

  setState(next) {
    if (next === this.state) return;
    this.state = next;
    if (!this.walk) return;
    if (next === "walk") this.walk.reset().play();
    else this.walk.stop();
  }

  hold(prop) {
    this.held = prop;
    this.group.add(prop);
    prop.position.set(0.35, 1.0, 0.2);
  }
}
