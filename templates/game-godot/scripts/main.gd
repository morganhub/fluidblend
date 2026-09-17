extends Node3D
## Test scene built in code, so the template holds no binary and no hand-edited scene tree:
## a floor, a wall to collide with, a prop to pick up, and the exported character under a
## controllable body. The character comes from `res://assets/character.glb` (fluidblend game.export).

const CHARACTER := "res://assets/character.glb"
const WALL_X := 2.0
const PICKUP_POSITION := Vector3(-1.5, 0.5, 0.0)

var player: CharacterBody3D
var pickup: Area3D


func _ready() -> void:
	_add_static_box("Floor", Vector3(0, -0.1, 0), Vector3(20, 0.2, 20))
	_add_static_box("Wall", Vector3(WALL_X, 1.0, 0), Vector3(0.2, 2.0, 4.0))
	player = preload("res://scripts/player.gd").new()
	player.name = "Player"
	add_child(player)
	var packed := load(CHARACTER) as PackedScene
	if packed != null:
		player.setup(packed.instantiate())
	pickup = preload("res://scripts/pickup.gd").new()
	pickup.name = "Pickup"
	pickup.position = PICKUP_POSITION
	add_child(pickup)
	var light := DirectionalLight3D.new()
	light.rotation_degrees = Vector3(-50, 30, 0)
	add_child(light)
	var camera := Camera3D.new()
	camera.position = Vector3(0, 2.2, 6.0)
	camera.rotation_degrees = Vector3(-12, 0, 0)
	add_child(camera)


func _add_static_box(node_name: String, at: Vector3, size: Vector3) -> void:
	var body := StaticBody3D.new()
	body.name = node_name
	body.position = at
	var shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = size
	shape.shape = box
	body.add_child(shape)
	var mesh := MeshInstance3D.new()
	var visual := BoxMesh.new()
	visual.size = size
	mesh.mesh = visual
	body.add_child(mesh)
	add_child(body)
