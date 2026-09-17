"""A diagnostic observes dependencies; only an explicit migration updates the lock."""

from pathlib import Path

from fluidblend.contracts.capabilities import CapabilitiesReport
from fluidblend.contracts.project import DependencyLock
from fluidblend.core.atomic import read_json
from fluidblend.core.hashing import sha256_file
from fluidblend.core.paths import resolve_inside


def verify_executable(project, capability_id: str, executable: str) -> None:
    """Refuse changed binaries when a production has pinned their content."""
    path = resolve_inside(project.root, project.manifest.dependency_lock)
    if not path.exists():
        return
    lock = DependencyLock.model_validate(read_json(path))
    expected = lock.dependencies.get(capability_id)
    if expected and expected.sha256 and sha256_file(Path(executable)) != expected.sha256:
        raise ValueError(
            f"{capability_id} binary differs from dependency lock; use a migration branch and regression run"
        )


def compare_lock(path: Path, report: CapabilitiesReport) -> dict:
    if not path.exists():
        return {"status": "not_locked", "differences": [], "path": str(path)}
    lock = DependencyLock.model_validate(read_json(path))
    differences = []
    for name, expected in lock.dependencies.items():
        actual = report.get(name)
        # Entries recording absent optional tools do not make them mandatory.
        if expected.status not in ("available", "unverified"):
            continue
        if actual is None or actual.status not in ("available", "unverified"):
            differences.append(
                {
                    "dependency": name,
                    "field": "status",
                    "expected": expected.status,
                    "observed": actual.status if actual else "missing",
                }
            )
            continue
        for field, value in (("version", actual.version), ("sha256", actual.evidence.get("sha256"))):
            wanted = getattr(expected, field)
            if name == "blender.batch" and field == "version":
                wanted = wanted.removesuffix(" LTS") if wanted else wanted
                value = value.removesuffix(" LTS") if value else value
            if wanted is not None and wanted != value:
                differences.append(
                    {"dependency": name, "field": field, "expected": wanted, "observed": value}
                )
    return {"status": "mismatch" if differences else "matched", "differences": differences, "path": str(path)}
