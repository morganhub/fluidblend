"""Web target: the exported GLB loaded and played by Three.js in a real headless browser (§14).

Same rule as the Godot target: a generated folder proves nothing. `import_test` loads the GLB in the
engine and reads what it found; `smoke_test` plays the template through keyboard events and reads the
page's own report. The browser also renders: a screenshot and the share of the frame the character
covers are the only evidence the kit has of the skin drawn by a game engine.

The page is served on 127.0.0.1, on an ephemeral port, for the duration of the run, because a
browser refuses to load a GLB from `file://`. The browser is started offline: every host but
127.0.0.1 resolves to nothing.
"""

import functools
import html
import http.server
import json
import re
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from fluidblend.adapters.tool_paths import find_browser
from fluidblend.contracts.common import ErrorCode
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.project import kit_root
from fluidblend.hostops.context import HostOpError

TEMPLATE = "templates/game-web"
CHARACTER = "assets/character.glb"
REPORT = re.compile(r'<pre id="fluidblend-report">(.*?)</pre>', re.S)
# Below this share of the frame the character is a few stray pixels, not a drawn skin.
MIN_RENDERED_SHARE = 0.01


class _Handler(http.server.SimpleHTTPRequestHandler):
    # Windows takes MIME types from the registry, where `.js` is often text/plain: a browser then
    # refuses every ES module. The types the page needs are stated here instead.
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".html": "text/html",
        ".json": "application/json",
        ".glb": "model/gltf-binary",
    }

    def log_message(self, *args):  # noqa: ARG002 - the engine's stdout is a JSON result
        pass


@contextmanager
def served(folder):
    """Serve `folder` on 127.0.0.1 and yield its base URL."""
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(_Handler, directory=str(folder))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def browser_for(ctx):
    tool = find_browser(ctx.project.local.browser_executable)
    if not tool:
        raise HostOpError(
            ErrorCode.MISSING_DEPENDENCY,
            "no Chrome or Edge found: the web game target stays not_tested",
            recovery="install Microsoft Edge or Google Chrome, or set browser_executable in config/local.json",
        )
    return tool


def run_browser(ctx, browser, arguments, what):
    remaining = ctx.project.manifest.budgets.max_task_minutes * 60 - (
        time.monotonic() - ctx.started_monotonic
    )
    if remaining <= 0:
        raise HostOpError(ErrorCode.BUDGET_EXCEEDED, "game task time budget exhausted")
    profile = ctx.task_dir / f"browser-profile-{time.monotonic_ns()}"
    command = [
        browser,
        "--headless=new",
        "--no-first-run",
        "--disable-extensions",
        "--disable-background-networking",
        "--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE 127.0.0.1",
        f"--user-data-dir={profile}",
        # Software GL when the machine has no usable GPU: slower, same pixels to read back.
        "--enable-unsafe-swiftshader",
        # Virtual time: the page's loading and timers run to completion before the DOM is dumped.
        "--virtual-time-budget=60000",
        *arguments,
    ]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=min(remaining, 300),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"browser {what} did not complete: {exc}") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def browser_version(browser):
    # Chromium browsers on Windows ignore --version: the binary is identified by its hash.
    return {"executable": browser, "sha256": sha256_file(Path(browser))}


def page_report(ctx, browser, base):
    """Run `?smoke=1` and return the page's own report, or refuse: no report, no proof."""
    done = run_browser(ctx, browser, ["--dump-dom", f"{base}/index.html?smoke=1"], "smoke run")
    found = REPORT.search(done.stdout or "")
    if not found or not found.group(1).strip():
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "the page wrote no report: the run proves nothing",
            details={"exit_code": done.returncode, "stderr": (done.stderr or "")[-1500:]},
        )
    try:
        return json.loads(html.unescape(found.group(1)))
    except ValueError as exc:
        raise HostOpError(ErrorCode.VALIDATION_FAILED, f"unreadable page report: {exc}") from exc


def is_web_game(folder):
    return (folder / "index.html").is_file() and (folder / "test" / "smoke.js").is_file()


def vendor_problems(game):
    """Vendored engine files that differ from the hashes pinned in the kit."""
    pinned = read_json(kit_root() / TEMPLATE / "vendor" / "VENDOR.json")["files"]
    problems = []
    for name, expected in pinned.items():
        path = game / "vendor" / "three" / name
        if not path.is_file() or sha256_file(path) != expected:
            problems.append(name)
    return problems


def import_test(ctx, glb):
    browser = browser_for(ctx)
    game = ctx.out_dir / "game"
    shutil.copytree(kit_root() / TEMPLATE, game, ignore=shutil.ignore_patterns(".gitkeep"))
    shutil.copy2(glb, game / CHARACTER)
    with served(game) as base:
        report = page_report(ctx, browser, base)
    if not report.get("loaded"):
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "Three.js did not load the character",
            details={"error": report.get("error"), "engine": report.get("engine")},
        )
    for path in sorted(p for p in game.rglob("*") if p.is_file()):
        ctx.add_file("game", path)
    ctx.write_report(
        "game-import.json",
        {
            "template": TEMPLATE,
            "engine": report.get("engine"),
            "browser": browser_version(browser),
            "export_path": ctx.params.export_path,
            "export_sha256": sha256_file(glb),
            "game_dir": "game",
            "clips": report.get("clips", []),
            "walk_clip": report.get("clip"),
            "skinned_meshes": report.get("skinned_meshes"),
            "limits": ["load only: read game.smoke_test for the played prototype and the rendered frame"],
        },
    )
    ctx.metrics.update({"imported": True, "clips": len(report.get("clips", []))})
    ctx.next_safe_actions.append("game.smoke_test with game_dir = the published game folder")
    ctx.next_safe_actions.append("fluidblend preview web --game-dir <that folder> to play it yourself")


def smoke_test(ctx, source):
    browser = browser_for(ctx)
    tampered = vendor_problems(source)
    if tampered:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "vendored Three.js files differ from the kit's pinned hashes",
            details={"files": tampered},
        )
    started = time.monotonic()
    with served(source) as base:
        report = page_report(ctx, browser, base)
        shot = ctx.out_dir / "web-frame.png"
        run_browser(
            ctx,
            browser,
            ["--window-size=960,540", f"--screenshot={shot}", f"{base}/index.html?shot=1"],
            "screenshot",
        )
    wall_time_ms = round((time.monotonic() - started) * 1000)
    if shot.is_file():
        ctx.add_file("frame", shot)
    failed = [c["name"] for c in report.get("checks", []) if not c.get("passed")]
    share = report.get("rendered_share")
    # No WebGL context is a stated limit, not a failure; a context that draws nothing is a failure.
    if share is not None and share < MIN_RENDERED_SHARE:
        failed.append("character_is_rendered")
    passed = report.get("passed") is True and not failed
    limits = ["template gameplay only: two states, one wall, one pickup; not the user's game"]
    if share is None:
        limits.append("the browser gave no WebGL context: nothing was rendered, the skin is not verified")
    else:
        limits.append(
            "one rendered frame looked at by nobody yet: open web-frame.png before claiming the skin is right"
        )
    ctx.write_report(
        "game-smoke.json",
        {
            "game_dir": ctx.params.game_dir,
            "engine": report.get("engine"),
            "browser": browser_version(browser),
            "passed": passed,
            "checks": report.get("checks", []),
            "failed_checks": failed,
            "walk_clip": report.get("clip"),
            "root_motion_removed_m": report.get("root_motion_removed_m"),
            "recentered_m": report.get("recentered_m"),
            "skinned_meshes": report.get("skinned_meshes"),
            "webgl": report.get("webgl"),
            "rendered_share": share,
            "frame": "web-frame.png" if shot.is_file() else None,
            "wall_time_ms": wall_time_ms,
            "limits": limits,
        },
    )
    ctx.metrics.update(
        {
            "passed": passed,
            "checks": len(report.get("checks", [])),
            "failed_checks": failed,
            "rendered_share": share,
        }
    )
    if not passed:
        raise HostOpError(
            ErrorCode.VALIDATION_FAILED,
            "the web prototype ran and failed its smoke test",
            details={"failed_checks": failed, "report": json.dumps(report)[:1500]},
        )
