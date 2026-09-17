extends CharacterBody3D
## Controllable character with two states, `idle` and `walk`. Keyboard arrows move it and the accept
## key picks a prop up; tests drive exactly the same path through `simulated_input` and
## `simulated_interact`, so what the smoke test proves is what a player gets.

const SPEED := 1.4
const GRAVITY := 9.8
const RADIUS := 0.3

var simulated_input := Vector2.ZERO
var simulated_interact := false
var state := "idle"
var nearby_pickup: Area3D = null
var held_prop: Node3D = null
var model: Node3D = null
var animation_player: AnimationPlayer = null
var walk_animation := ""


func _init() -> void:
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = RADIUS
	capsule.height = 1.8
	shape.shape = capsule
	shape.position = Vector3(0, 0.9, 0)
	add_child(shape)


func setup(character: Node3D) -> void:
	model = character
	add_child(model)
	animation_player = _find_animation_player(model)
	if animation_player != null:
		for animation_name in animation_player.get_animation_list():
			# The kit names clips `<instance>.<clip>`; any clip whose name says "walk" will do.
			if "walk" in String(animation_name).to_lower():
				walk_animation = animation_name
				# glTF carries no loop flag: an imported cycle plays once and stops.
				animation_player.get_animation(animation_name).loop_mode = Animation.LOOP_LINEAR
				break


func _find_animation_player(node: Node) -> AnimationPlayer:
	if node is AnimationPlayer:
		return node
	for child in node.get_children():
		var found := _find_animation_player(child)
		if found != null:
			return found
	return null


func _physics_process(delta: float) -> void:
	var input := simulated_input
	if input == Vector2.ZERO:
		input = Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity.x = input.x * SPEED
	velocity.z = input.y * SPEED
	velocity.y = 0.0 if is_on_floor() else velocity.y - GRAVITY * delta
	move_and_slide()
	if input.length() > 0.1 and model != null:
		model.rotation.y = atan2(input.x, input.y)
	_set_state("walk" if input.length() > 0.1 else "idle")
	if (simulated_interact or Input.is_action_just_pressed("ui_accept")) and nearby_pickup != null:
		simulated_interact = false
		held_prop = nearby_pickup.take(self)
		nearby_pickup = null


func _set_state(next: String) -> void:
	if next == state:
		return
	state = next
	if animation_player == null or walk_animation == "":
		return
	if state == "walk":
		animation_player.play(walk_animation)
	else:
		animation_player.stop()
