"""Headless entry point of the fluidblend runtime.

Launched by the engine:
    blender --background --factory-startup --offline-mode --python-exit-code 2 \
        --python entrypoint.py -- <request.json> <result.json> --fluidblend-task <task_id>

No dependency beyond the standard library and `bpy`.
"""

import os
import sys


def _args_after_separator(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return []


def main() -> None:
    args = _args_after_separator(sys.argv)
    if len(args) < 2:
        raise SystemExit("usage: entrypoint.py -- <request.json> <result.json> [--fluidblend-task ID]")
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import fluidblend_runtime

    fluidblend_runtime.main(args[0], args[1])


main()
