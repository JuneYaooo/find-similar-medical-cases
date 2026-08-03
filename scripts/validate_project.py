#!/usr/bin/env python3
"""Validate the standalone Skill package without third-party dependencies."""

from __future__ import annotations

import json
import py_compile
import re
import sys
from pathlib import Path
from typing import Iterable, List


ROOT = Path(__file__).resolve().parents[1]


def markdown_files() -> Iterable[Path]:
    yield ROOT / "SKILL.md"
    readme = ROOT / "README.md"
    if readme.exists():
        yield readme
    yield from sorted((ROOT / "references").glob("*.md"))


def validate_skill(errors: List[str]) -> None:
    path = ROOT / "SKILL.md"
    if not path.exists():
        errors.append("missing SKILL.md")
        return
    text = path.read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
    if not match:
        errors.append("SKILL.md must start with YAML frontmatter")
        return
    fields = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if not separator:
            errors.append(f"invalid SKILL.md frontmatter line: {line}")
            continue
        fields[key.strip()] = value.strip()
    if set(fields) != {"name", "description"}:
        errors.append("SKILL.md frontmatter must contain only name and description")
    name = fields.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
        errors.append("Skill name must use lowercase hyphen-case")
    if ROOT.name != name:
        errors.append(f"Skill folder {ROOT.name!r} must match name {name!r}")
    if not fields.get("description"):
        errors.append("Skill description must not be empty")
    if len(text.splitlines()) > 500:
        errors.append("SKILL.md must stay under 500 lines")


def validate_openai_yaml(errors: List[str]) -> None:
    path = ROOT / "agents" / "openai.yaml"
    if not path.exists():
        errors.append("missing recommended agents/openai.yaml")
        return
    text = path.read_text(encoding="utf-8")
    values = dict(
        re.findall(
            r'^\s{2}(display_name|short_description|default_prompt):\s+"([^"]*)"\s*$',
            text,
            re.M,
        )
    )
    missing = {"display_name", "short_description", "default_prompt"} - set(values)
    if missing:
        errors.append("agents/openai.yaml missing: " + ", ".join(sorted(missing)))
        return
    if not 25 <= len(values["short_description"]) <= 64:
        errors.append("short_description must be 25-64 characters")
    if "$find-similar-medical-cases" not in values["default_prompt"]:
        errors.append("default_prompt must mention $find-similar-medical-cases")


def validate_links(errors: List[str]) -> None:
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in markdown_files():
        text = path.read_text(encoding="utf-8")
        for target in pattern.findall(text):
            if "://" in target or target.startswith(("#", "mailto:")):
                continue
            relative = target.split("#", 1)[0]
            if relative and not (path.parent / relative).resolve().exists():
                errors.append(
                    f"broken relative link in {path.relative_to(ROOT)}: {target}"
                )


def validate_reference_structure(errors: List[str]) -> None:
    for path in sorted((ROOT / "references").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        if len(text.splitlines()) > 100 and "## Contents" not in text:
            errors.append(
                f"long reference requires a Contents section: {path.relative_to(ROOT)}"
            )


def validate_json(errors: List[str]) -> None:
    for path in sorted((ROOT / "references").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def validate_python(errors: List[str]) -> None:
    for path in sorted((ROOT / "scripts").glob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"Python compile failed for {path.relative_to(ROOT)}: {exc}")


def main() -> int:
    errors: List[str] = []
    validate_skill(errors)
    validate_openai_yaml(errors)
    validate_links(errors)
    validate_reference_structure(errors)
    validate_json(errors)
    validate_python(errors)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Project validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
