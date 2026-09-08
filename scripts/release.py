"""Validate the release identity and extract its exact changelog section."""

import argparse
import re
import subprocess
import tomllib
from pathlib import Path


def release_notes(tag: str, version: str, changelog: str) -> str:
    """Reject ambiguous version identities and empty or duplicate release notes."""
    if not re.fullmatch(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
        raise ValueError("Release tag must be vMAJOR.MINOR.PATCH")
    if tag != f"v{version}":
        raise ValueError("Release tag does not match pyproject.toml version")
    sections = re.split(r"^## ", changelog, flags=re.MULTILINE)[1:]
    matches = []
    for section in sections:
        heading, _, body = section.partition("\n")
        if heading == version or heading.startswith(version + " - "):
            matches.append(body.strip())
    if len(matches) != 1:
        raise ValueError("Changelog must contain exactly one section for the release version")
    if not any(line.startswith("- ") and line[2:].strip() for line in matches[0].splitlines()):
        raise ValueError("Release changelog must contain at least one entry")
    return matches[0] + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag")
    parser.add_argument("--notes", type=Path, required=True)
    args = parser.parse_args()
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    notes = release_notes(args.tag, project["version"], Path("CHANGELOG.md").read_text())
    # A publication can only use a tag whose exact commit is already on main.
    tagged = subprocess.check_output(
        ["git", "rev-parse", f"refs/tags/{args.tag}^{{commit}}"], text=True
    ).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if tagged != head:
        raise ValueError("Checked-out commit does not match the release tag")
    subprocess.run(["git", "merge-base", "--is-ancestor", head, "origin/main"], check=True)
    args.notes.write_text(notes, encoding="utf-8")


if __name__ == "__main__":
    main()
