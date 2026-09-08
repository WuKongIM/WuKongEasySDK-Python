"""Release metadata gates must fail before an immutable version is published."""

import runpy
from pathlib import Path

import pytest

release_notes = runpy.run_path(str(Path(__file__).parents[1] / "scripts/release.py"))[
    "release_notes"
]


def test_exact_release_section_excludes_other_versions():
    changelog = "## Unreleased\n- Future\n## 0.1.0 - 2026-09-08\n- Initial SDK\n## 0.0.9\n- Old\n"
    assert release_notes("v0.1.0", "0.1.0", changelog) == "- Initial SDK\n"


@pytest.mark.parametrize("tag", ["0.1.0", "main", "v0.1.0rc1", "v00.1.0", "v0.1.0\n"])
def test_rejects_invalid_release_tags(tag):
    with pytest.raises(ValueError, match="Release tag must"):
        release_notes(tag, "0.1.0", "## 0.1.0\n- Initial SDK\n")


def test_rejects_tag_version_mismatch():
    with pytest.raises(ValueError, match="does not match"):
        release_notes("v0.1.1", "0.1.0", "## 0.1.0\n- Initial SDK\n")


@pytest.mark.parametrize(
    "changelog",
    ["## Unreleased\n- Initial SDK", "## 0.1.0\n- First\n## 0.1.0 - 2026-09-08\n- Duplicate"],
)
def test_rejects_missing_or_duplicate_version_sections(changelog):
    with pytest.raises(ValueError, match="exactly one section"):
        release_notes("v0.1.0", "0.1.0", changelog)


@pytest.mark.parametrize("body", ["", "### Added\n", "- \n"])
def test_rejects_empty_release_entries(body):
    with pytest.raises(ValueError, match="at least one entry"):
        release_notes("v0.1.0", "0.1.0", "## 0.1.0\n" + body)
