# Contributing

Please read this before opening a pull request.

## Principles

- **No feature is announced without proof.** An operation is available only if it is implemented,
  tested against the real locked Blender and documented; otherwise it stays `available=false` in
  `src/fluidblend/contracts/operations.py` and answers `UNSUPPORTED_CAPABILITY`.
- **Blender is locked**: the 5.2 LTS series. The runtime (`blender_runtime/`) uses only the standard
  library and `bpy`; the legacy Actions API (`Action.fcurves`) is forbidden by a test.
- **The kit installs nothing globally** and never modifies a project's `config/permissions.json`.
- Code, identifiers, commit messages and user documentation are in English.

## Environment

```powershell
uv sync --python 3.13
uv run ruff check src blender_runtime tests
uv run ruff format src blender_runtime tests
uv run fluidblend schema export --out schemas     # after any contract change
uv run pytest tests/unit -q                       # without Blender
uv run pytest tests -q --acceptance-report docs/acceptance-reports/latest-p0   # with Blender 5.2
```

The full acceptance suite opens a Blender window for a few seconds: scenario A03, and the live
scenarios L01 to L09, which also need the MCP add-on, the kit's runtime add-on
(`uv run fluidblend runtime install --enable`), `uvx`, and port 9876 free. Each of those tests
creates and stops its own Blender process, and declares itself `not_run` rather than touching a
session it did not open.

## Pull requests

1. One topic per PR, with the matching tests (unit, plus Blender if the runtime changes).
2. `docs/cli.md`, `docs/architecture.md` and the skill (`skills/fluidblend/`) updated if the visible
   behaviour changes.
3. `CHANGELOG.md` updated.
4. No binary in the repository without a recorded license (`fixtures/README.md`).

## Reporting a problem

Attach the output of `uv run fluidblend doctor --json` (it contains neither secrets nor scene
content) and, if a task failed, the `state/tasks/<task_id>/` folder of the project concerned.
