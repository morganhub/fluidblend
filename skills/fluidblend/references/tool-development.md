# Adjustment tools generated on demand

## Status: not implemented (lot P1) — what to do

`tool.inspect`, `tool.test` and `tool.register` are declared with `available=false` and answer
`UNSUPPORTED_CAPABILITY` (exit 2). So do `adjustment.preview`, `adjustment.apply` and
`adjustment.revert`. The `tools/custom/` folder is created by the scaffold but stays **empty**: there
is no tool registry, no loading mechanism and no Blender panel in this lot.

Typical requests concerned: "make this gesture wider", "slow down the anticipation only", "fix the
sliding foot", "keep the hand on this handle", "add a slider to tune the gaze".

What to do:

1. **Stop.** Do not write a `bpy` script in `tools/custom/`, do not run it through a workaround, do
   not present it as a delivered tool.
2. **Explain** that generating adjustment tools belongs to lot 3 and assumes a rig with IK controls,
   a clip library and a reversible preview mechanism — three things missing from lot P0.
3. **Offer what exists**: `animation.retime` covers the only implemented adjustment, namely changing
   the duration of a whole clip into a variant. It handles neither a partial segment, nor amplitude,
   nor gaze, nor contact.
4. **Do not requalify the request.** "Slow down the anticipation only" is not `animation.retime`: the
   P0 retime stretches the entire clip. Say so instead of delivering a silent approximation.

## Tool contract (to be honored the day lot 3 opens)

Every registered tool will have to declare, without exception:

| Field | Content |
| --- | --- |
| identifier, version | stable, versioned |
| purpose | what the tool does, in one verifiable sentence |
| supported rigs | explicit profiles; outside the list = refusal, not degradation |
| parameters | bounds and units for each one |
| time scope | the `[start, end_exclusive)` window affected |
| affected channels | bones and properties touched, protected channels excluded |
| preconditions | required scene state |
| preview mode | how to see the effect without applying it |
| effects on sources | what is modified, what is copied |
| rollback method | how to return to the previous state |
| tests | unit tests and a Blender fixture |
| known limits | cases not handled, named |

Mandatory life cycle: targeted specification → code → unit tests → Blender fixture →
before/after preview → measurement → registration as a validated capability. A button wired to an
empty function is not a tool. An algorithm that only handles one case must be **named and documented
as such**.

Permanent prohibitions, including while developing a tool: modifying the security core
(`core/paths.py`, `core/permissions.py`, `core/locks.py`), relaxing a threshold in
`config/quality.json` to make a result pass, deleting or neutralizing an acceptance test.

## Planned adjustments (lot 3, not available)

| Tool | Function | Essential verification |
| --- | --- | --- |
| `retime_segment` | change the duration of a portion and move the associated events | order of keys and events preserved |
| `scale_gesture` | change the amplitude of allowed channels | rig limits and contacts preserved |
| `look_at_target` | set gaze target, influence and speed | no abrupt flip, no out-of-limit rotation |
| `contact_lock` | stabilize a hand or a foot over a given window | contact error measured in the right space |
| `root_path_adjust` | move the global trajectory | no double application of the translation |
| `loop_cleanup` | fix a loop seam | pose continuity and, if requested, velocity continuity |
| `curve_cleanup` | reduce noise or redundant keys | maximum deviation under threshold, contacts untouched |
| `expression_strength` | modulate an available expression | shape key bounds, combination with the lips |

`contact_lock` and `curve_cleanup` are explicitly **bounded** pieces of development, not universal
solvers. A stance lock must distinguish intentional stance, walking and deliberate sliding; if it
cannot, it must not be offered.

Implementations under consideration, leaning on native Blender rather than home-made code:
`graph.decimate` in `ERROR` mode, `graph.clean` and `graph.euler_filter` for curve cleanup; the
`CYCLES` F-modifier plus `pose.propagate(mode='LAST_KEY')` and a continuity measurement for looping;
bounded `TRACK_TO` or `DAMPED_TRACK` constraints then a bake for gaze; a windowed `COPY_LOCATION`
then `nla.bake(visual_keying=True, clear_constraints=True)` for contact.

## Blender panel (lot 3, not available)

A `Director` panel is planned inside Blender: target selection, parameters, interval, `Preview`,
`Apply`, `Revert`, status and a link to the report. The widgets would call **the same operations** as
the CLI, never a parallel logic.

Constraints already settled: bounded, responsive sliders that do not accumulate hundreds of
keyframes on every drag; preview on a variant or on a reversible temporary state; debounce through
`bpy.app.timers`, which restricts the panel to GUI mode since timers do not fire under
`--background`; a confirmation creates an explicit new revision.

A possible HTML/JS interface belongs to P2. If it ever happens: modern JavaScript, English variable
names, `let` rather than `var`, no `var`, no jQuery, no heavy framework for a simple panel.

## Related acceptance scenario

Scenario B08 ("ask for a missing tool on an unsupported rig" → a bounded tool with a test, or a clear
limitation, never a false success) belongs to the P1 acceptance plan. It is not executed in this lot.
The rule it encodes applies today nonetheless: faced with an out-of-scope request, the only
acceptable answer is a clear statement of the limitation.
