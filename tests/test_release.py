"""Exercise release metadata updates through their command-line entry points."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
VERSION_FILES = [
    "package.json",
    "package-lock.json",
    "src/roundtable/web/package.json",
    "src/roundtable/web/package-lock.json",
    "pyproject.toml",
    "src/roundtable/__init__.py",
    "src/skills/SKILL.md",
    "SKILL.md",
    "uv.lock",
]


@pytest.fixture
def release_repo(tmp_path: Path) -> Path:
    for filename in [*VERSION_FILES, "scripts/release/bump-version.js", "scripts/release/changelog.js"]:
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPOSITORY / filename, target)
    subprocess.run(["git", "init", "--quiet"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Release Test",
            "-c",
            "user.email=release@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "fix: release fixture",
        ],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_version_bump_updates_all_declarations_and_keeps_dry_run_read_only(release_repo: Path, newline: bytes) -> None:
    for filename in VERSION_FILES:
        path = release_repo / filename
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline))
    before = {filename: (release_repo / filename).read_bytes() for filename in VERSION_FILES}
    command = ["node", "scripts/release/bump-version.js", "--type=patch"]
    subprocess.run([*command, "--dry-run"], cwd=release_repo, check=True, capture_output=True)
    assert before == {filename: (release_repo / filename).read_bytes() for filename in VERSION_FILES}

    result = subprocess.run(command, cwd=release_repo, check=True, capture_output=True, encoding="utf-8")
    version = result.stdout.strip()
    for filename in VERSION_FILES[:4]:
        data = json.loads((release_repo / filename).read_text(encoding="utf-8"))
        assert data["version"] == version
        if "packages" in data:
            assert data["packages"][""]["version"] == version
    assert f'version = "{version}"' in (release_repo / "pyproject.toml").read_text(encoding="utf-8")
    assert f'__version__ = "{version}"' in (release_repo / "src/roundtable/__init__.py").read_text(encoding="utf-8")
    assert f'name = "agent-roundtable"\nversion = "{version}"' in (release_repo / "uv.lock").read_text(encoding="utf-8")
    source = (release_repo / "src/skills/SKILL.md").read_text(encoding="utf-8")
    assert f"version: {version}\n" in source
    assert (release_repo / "SKILL.md").read_text(encoding="utf-8") == source.replace(
        "references/", "src/skills/references/"
    )


@pytest.mark.parametrize("notes", ["", "### Fixed\n\n- Preserve curated 中文 notes.\n\n"])
def test_changelog_releases_unreleased_section(release_repo: Path, notes: str) -> None:
    changelog = release_repo / "CHANGELOG.md"
    previous = "## [1.0.0] - 2026-01-01\n\n- Previous release.\n"
    original = f"# Changelog\n\n## [Unreleased]\n\n{notes}{previous}"
    changelog.write_text(original, encoding="utf-8")
    command = ["node", "scripts/release/changelog.js", "--version=3.0.0"]
    preview = subprocess.run(
        [*command, "--dry-run"], cwd=release_repo, check=True, capture_output=True, encoding="utf-8"
    )
    assert changelog.read_text(encoding="utf-8") == original
    subprocess.run(command, cwd=release_repo, check=True, capture_output=True)
    result = changelog.read_text(encoding="utf-8")
    assert result in preview.stdout
    assert result.startswith("# Changelog\n\n## [Unreleased]\n\n## [3.0.0] - ")
    assert result.endswith(previous)
    assert notes or "release fixture" in result
    assert notes in result
