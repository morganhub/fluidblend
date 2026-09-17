# Binary assets and dependency migrations

The repository and generated projects track `.blend`, `.glb`, `.wav` and `.mp4` with Git LFS.
Install Git LFS before adding binary assets, run `git lfs install --local` in the production
repository, and verify `git lfs ls-files` before committing. Keep generated renders and caches
out of Git unless they are intentionally selected acceptance fixtures.

A fresh clone must run `git lfs pull` and `git lfs fsck`. A text LFS pointer is not a usable asset.
Every reference asset also requires a license, source revision, SHA-256 and reproduction recipe.
`pytest tests/integration/test_lfs_roundtrip.py` verifies push and fresh-clone recovery against a
disposable local bare remote using the actual skinned Vitruvian fixture, without changing this repository's index, history or remotes.
Hosted remote authentication and quota remain specific to the production remote.

`fluidblend doctor --project .` observes dependencies and compares versions and hashes with the
project lock; it does not update it. A mismatch returns exit 2. Missing locks are reported as
`not_locked`, preserving existing P0 projects. Use `--write-lock <path>` explicitly to capture a
candidate lock. Do not update an active production lock simply to silence a mismatch.

For an update, create a migration branch, capture the proposed lock, run the unit and real Blender
acceptance suites plus the production's own fixtures, compare renders and measurements, and record
the review. Commit the accepted lock with the migration. Other Blender series are unsupported
until a dedicated compatibility run is recorded. Old technical reports without `evidence.json`
must be regenerated before they can validate the current scene.
