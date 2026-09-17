# Previews, video and film

Status: **implemented (lot P0)** for `shot.preview`, `shot.validate`, `film.assemble`.
**Not implemented (lot P1)**: `shot.build`, `audio.prepare`.

## `shot.preview`

Renders a PNG sequence from the shot's latest work version, then assembles it into an MP4 if FFmpeg
is available.

```json
{
  "schema_version": "1.0",
  "operation": "shot.preview",
  "operation_id": "preview-shot010-blocking-001",
  "project_id": "demo-studio",
  "target": {"shot_id": "shot010"},
  "parameters": {
    "frame_start": 1,
    "frame_end_exclusive": 241,
    "step": 1,
    "engine": "WORKBENCH",
    "width": 640,
    "height": 360,
    "label": "blocking"
  },
  "dry_run": false
}
```

| Parameter | Default | Notes |
| --- | --- | --- |
| `frame_start` | the scene range | integer |
| `frame_end_exclusive` | the scene range | exclusive bound; 241 = up to frame 240 |
| `step` | 1 | 1 to 100; a step > 1 shortens the video, a warning reports it |
| `engine` | the project's `preview.engine` | `WORKBENCH` or `EEVEE` |
| `width`, `height` | `preview.width/height` | 16 to 8192 |
| `label` | `preview` | free-form label, `[A-Za-z0-9._-]` |

Rendering is **idempotent**: `use_overwrite = False` and `use_placeholder = True`, so a frame that is
already written is not recomputed. The file pattern is `frame_%04d.png` (RGB 8-bit). A single missing
frame fails the operation (`VALIDATION_FAILED`) with the list of absent frames.

The requested frame count is checked twice: by the engine before launch (`BUDGET_EXCEEDED`, exit 6)
and by the runtime itself against `max_preview_frames`.

Choice of engine: Workbench for blocking and timing checks, EEVEE for visual review. Order of
magnitude measured at 640x360: Workbench under 0.2 s per frame (the demo scene's 240 frames rendered
in 17.3 s during the last acceptance run), EEVEE about 2 s per frame including shader compilation —
that is several minutes for 240 frames. Announce the cost before launching an EEVEE preview, and
read the current value in `state/metrics.json` rather than assuming.

## Video assembly

The host post-processing calls FFmpeg, then ffprobe:

```
ffmpeg -y -v error -framerate <num>/<den> -start_number <first> -i frame_%04d.png \
  -c:v libx264 -crf 18 -preset medium -vf scale=trunc(iw/2)*2:trunc(ih/2)*2 \
  -pix_fmt yuv420p -movflags +faststart preview.mp4
ffprobe -v error -print_format json -show_format -show_streams -count_frames preview.mp4
```

The operation fails if `nb_read_frames` differs from the number of frames produced, or if
`r_frame_rate` does not match the project frame rate exactly. The evidence is kept in `ffprobe.json`.

If `ffmpeg` or `ffprobe` is missing, the frames are published **without a video**, a warning is
emitted and the `video` metric is `not_run`. That is not a failure, but it is not a video either:
say it as it is.

Artifacts published in `renders/<shot>/<operation_id>/`: `frames/` (the PNGs),
`render-report.json` (engine, resolution, range, step, frame rate, pattern, camera, duration, seconds
per frame, expected/produced/missing frames), `preview.mp4`, `ffprobe.json`. Every measured render
duration feeds `state/metrics.json` and sharpens the following budget estimates.

## `shot.validate`

```powershell
fluidblend validate --project . --target shot010
fluidblend validate --project . --target shot010 --no-preview
```

Host operation, it **changes nothing**. Checks:

| Check | Passes when |
| --- | --- |
| `work_version_exists` | a version `shots/<shot>/work/vNNN/<shot>.blend` exists |
| `revision_hash_matches` | the file's sha256 matches the recorded revision |
| `preview_exists` | an `ffprobe.json` is published (unless `--no-preview`) |
| `preview_frame_count` | the video's `nb_read_frames` = `expected_frames` in the render report |
| `preview_frame_rate` | `r_frame_rate` = the project frame rate |
| `preview_pix_fmt` | `yuv420p` |
| `latest_audit_passed` | the latest published `audit.json` passed |

The `shot-validation.json` report contains `technical_pass`, the list of checks with their detail,
and `suggested_validation_state`. The command exits 1 (`FAILED`) when `technical_pass` is false.

**`technical_pass` is not `art_approved`.** The report states this explicitly. Moving a shot to
`visual_review_pending` or `art_approved` in `shot.json` is a human decision. Evidence of art
validation cites the frames actually looked at and the checks that are missing; five inspected images
do not validate a film.

## `film.assemble`

Concatenates the already published previews of the listed shots, in the given order.

```json
{
  "schema_version": "1.0",
  "operation": "film.assemble",
  "operation_id": "assemble-demo-001",
  "project_id": "demo-studio",
  "target": {},
  "parameters": {"shot_ids": ["shot010"], "output_name": "film-preview"},
  "dry_run": false
}
```

- `shot_ids`: at least one shot. For each of them, the most recently published `preview.mp4` is
  used. If a shot has no preview, the operation fails and states that `shot.preview` must be run on
  that shot.
- `output_name`: name of the produced file, without extension.
- `audio_path` (optional): path **relative to the project**, resolved and verified. An external
  absolute path, a `..`, a UNC path or a protected path is refused (`PERMISSION_REQUIRED`, status
  `blocked`, exit 2): outside the approved scope, no effect.
  The audio is encoded as AAC 192 kb/s at 48 kHz with `-shortest`; the video is copied without
  re-encoding.

Final check: the sum of the inputs' `nb_read_frames` must equal that of the output, otherwise the
operation fails. Artifacts published in `renders/project/<operation_id>/`: `<output_name>.mp4` and
`ffprobe.json`.

FFmpeg and ffprobe are **mandatory** here: their absence gives `MISSING_DEPENDENCY` (exit 2), not a
silent fallback.

## Audio preparation and analysis

`audio.prepare` reads project-relative `source_path` (including protected `audio/source/`).
It writes a new mono PCM16 48 kHz WAV using FFmpeg loudnorm in two passes with mandatory
resampling. Bounds/defaults for integrated LUFS, true peak and loudness range are in the schema.
The report records source hash, measured passes, sample count and rational seconds/frame duration.

`lipsync.analyze` accepts `source_path`, invokes Rhubarb 1.14 phonetic analysis and validates
ordered A–H/X mouth cues. It does not animate the face or approve dialogue. `lipsync.apply`
and `expression.apply` remain unavailable. Do not promise a dialogued shot from analysis alone.

Local append `shot.build` is available; read the character reference for asset admission.
Sequence organization, linked assets, facial fixtures, final renders and recorded human approval
remain future work. `shot.validate` requires audit/preview evidence bound to the current revision
and scene hash; regenerate stale evidence before claiming technical validity.
