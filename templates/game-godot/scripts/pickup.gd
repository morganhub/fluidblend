extends Area3D
## A prop lying on the ground. A body that enters the area may take it: the visible prop is then
## reparented to that body, in its hand height, and the area stops offering it.

var prop: MeshInstance3D


func _init() -> void:
	var shape := CollisionShape3D.new()
	var sphere := SphereShape3D.new()
	sphere.radius = 0.7
	shape.shape = sphere
	add_child(shape)
	prop = MeshInstance3D.new()
	prop.name = "Prop"
	var box := BoxMesh.new()
	box.size = Vector3(0.2, 0.2, 0.2)
	prop.mesh = box
	add_child(prop)
	body_entered.connect(_on_body_entered)
	body_exited.connect(_on_body_exited)


func _on_body_entered(body: Node) -> void:
	if prop != null and "nearby_pickup" in body:
		body.nearby_pickup = self


func _on_body_exited(body: Node) -> void:
	if "nearby_pickup" in body and body.nearby_pickup == self:
		body.nearby_pickup = null


func take(holder: Node3D) -> Node3D:
	var taken := prop
	prop = null
	remove_child(taken)
	holder.add_child(taken)
	taken.position = Vector3(0.35, 1.0, 0.0)
	return taken
