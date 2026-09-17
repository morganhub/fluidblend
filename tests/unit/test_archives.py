import stat
import zipfile

import pytest

from fluidblend.core.archives import ArchiveLimits, extract_zip


def test_archive_extracts_once_without_overwrite(tmp_path):
    with zipfile.ZipFile(tmp_path / "asset.zip", "w") as z:
        z.writestr("folder/mesh.txt", "asset")
    assert extract_zip(tmp_path, "asset.zip", "assets/version1") == ["folder/mesh.txt"]
    assert (tmp_path / "assets/version1/folder/mesh.txt").read_text() == "asset"
    with pytest.raises(ValueError, match="exists"):
        extract_zip(tmp_path, "asset.zip", "assets/version1")


@pytest.mark.parametrize(
    "names", [["../escape"], ["C:/escape"], ["/escape"], ["A.txt", "a.txt"], ["foo:bar"]]
)
def test_archive_rejects_escaping_and_colliding_members(tmp_path, names):
    with zipfile.ZipFile(tmp_path / "asset.zip", "w") as z:
        for name in names:
            z.writestr(name, "asset")
    with pytest.raises(ValueError):
        extract_zip(tmp_path, "asset.zip", "imported")
    assert not (tmp_path / "imported").exists()


def test_archive_rejects_expansion_and_links(tmp_path):
    with zipfile.ZipFile(tmp_path / "asset.zip", "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("huge", "0" * 100_000)
    for limits in [
        ArchiveLimits(max_expanded_bytes=100),
        ArchiveLimits(max_files=0),
        ArchiveLimits(max_expansion_ratio=2),
    ]:
        with pytest.raises(ValueError):
            extract_zip(tmp_path, "asset.zip", "imported", limits=limits)
    with zipfile.ZipFile(tmp_path / "asset.zip", "w") as z:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, "../outside")
    with pytest.raises(ValueError, match="links"):
        extract_zip(tmp_path, "asset.zip", "imported")
