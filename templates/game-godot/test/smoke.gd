extends SceneTree
## Headless smoke test, no third-party test framework:
##   godot --headless --path <project> -s res://test/smoke.gd -- --report <file.json>
## It plays the real main scene through the same input path a player uses, writes one JSON report
## and exits 0 only if every check passed. A missing report means the run proves nothing.

const MAIN := "res://scenes/main.tscn"
const FRAMES_TO_WALL := 240
const FRAMES_TO_PICKUP := 420

var checks: Array = []


func _initialize() -> void:
	_run.call_deferred()


func check(check_name: String, passed: bool, detail: Variant = null) -> void:
	checks.append({"name": check_name, "passed": passed, "detail": detail})


func step(frames: int) -> void:
	for _i in frames:
		await physics_frame


func _run() -> void:
	var started := Time.get_ticks_msec()
	var packed := load(MAIN) as PackedScene
	check("main_scene_loads", packed != null)
	if packed == null:
		_finish(started)
		return
	var main := packed.instantiate()
	root.add_child(main)
	await step(5)
	var player = main.get("player")
	check("character_model_instantiated", player != null and player.model != null)
	check("animation_player_found", player != null and player.animation_player != null)
	check(
		"walk_animation_found",
		player != null and player.walk_animation != "",
		player.walk_animation if player != null else null
	)
	if player == null or player.animation_player == null:
		_finish(started)
		return
	await step(30)
	check("stands_on_floor", player.is_on_floor() and absf(player.position.y) < 0.05, player.position.y)
	check("idle_state_plays_nothing", player.state == "idle" and not player.animation_player.is_playing())

	player.simulated_input = Vector2(1, 0)
	await step(FRAMES_TO_WALL)
	var limit: float = main.WALL_X - 0.1 - player.RADIUS
	check("walk_state_plays_walk_clip", player.state == "walk" and player.animation_player.is_playing())
	check("character_moved", player.position.x > 0.5, player.position.x)
	check("wall_stops_character", player.position.x <= limit + 0.02, [player.position.x, limit])

	player.simulated_input = Vector2(-1, 0)
	var walked := 0
	while player.nearby_pickup == null and walked < FRAMES_TO_PICKUP:
		await physics_frame
		walked += 1
	player.simulated_input = Vector2.ZERO
	await step(5)
	check("back_to_idle", player.state == "idle" and not player.animation_player.is_playing())
	check("reached_pickup", player.nearby_pickup != null, player.position.x)
	player.simulated_interact = true
	await step(5)
	check("prop_is_held", player.held_prop != null and player.held_prop.get_parent() == player)
	check("pickup_is_empty", main.pickup.prop == null)
	_finish(started)


func _finish(started: int) -> void:
	var passed := true
	for item in checks:
		passed = passed and item["passed"]
	var report := {
		"engine": Engine.get_version_info()["string"],
		"headless": DisplayServer.get_name() == "headless",
		"physics_ticks_per_second": Engine.physics_ticks_per_second,
		"wall_time_ms": Time.get_ticks_msec() - started,
		"checks": checks,
		"passed": passed,
	}
	var arguments := OS.get_cmdline_user_args()
	var index := arguments.find("--report")
	if index >= 0 and index + 1 < arguments.size():
		var file := FileAccess.open(arguments[index + 1], FileAccess.WRITE)
		if file != null:
			file.store_string(JSON.stringify(report, "  "))
			file.close()
	print("FLUIDBLEND_SMOKE=" + JSON.stringify({"passed": passed, "checks": checks.size()}))
	quit(0 if passed else 1)
