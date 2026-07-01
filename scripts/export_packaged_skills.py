#!/usr/bin/env python3
"""Export canonical packaged SPEDAS Agent Kit skills into a runtime wrapper.

The source of truth is ``src/spedas_agent_kit/resources/skills``. Runtime
wrappers can use this helper to materialize the shared skill set into their own
``skills/`` directory without copying science workflow logic by hand.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "spedas_agent_kit" / "resources" / "skills"


@dataclass(frozen=True)
class ExportReport:
    source: str
    target: str
    dry_run: bool
    clean: bool
    skills_count: int
    copied: list[str]
    updated: list[str]
    unchanged: list[str]
    removed: list[str]


def _skill_dirs(source: Path) -> list[Path]:
    return sorted(
        p for p in source.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )


def _relative_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path.relative_to(root)


def _copy_skill(src: Path, dst: Path, *, dry_run: bool) -> str:
    if not dst.exists():
        if not dry_run:
            shutil.copytree(src, dst)
        return "copied"

    changed = False
    for rel in _relative_files(src):
        src_file = src / rel
        dst_file = dst / rel
        if not dst_file.exists() or not filecmp.cmp(src_file, dst_file, shallow=False):
            changed = True
            if not dry_run:
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)

    # Remove files that no longer exist in the source copy for this skill. Keep
    # directory cleanup simple and local to this skill directory.
    src_files = set(_relative_files(src))
    for rel in list(_relative_files(dst)):
        if rel not in src_files:
            changed = True
            if not dry_run:
                (dst / rel).unlink()

    if not dry_run:
        for directory in sorted((p for p in dst.rglob("*") if p.is_dir()), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass

    return "updated" if changed else "unchanged"


def export_skills(source: Path, target: Path, *, dry_run: bool, clean: bool) -> ExportReport:
    source = source.resolve()
    target = target.resolve()

    if not source.exists():
        raise FileNotFoundError(f"skill source does not exist: {source}")
    if not source.is_dir():
        raise NotADirectoryError(f"skill source is not a directory: {source}")
    if source == target or source in target.parents:
        raise ValueError("target must not be the packaged skill source or inside it")

    skills = _skill_dirs(source)
    if not skills:
        raise ValueError(f"no skills with SKILL.md found under {source}")

    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []
    for skill in skills:
        status = _copy_skill(skill, target / skill.name, dry_run=dry_run)
        {"copied": copied, "updated": updated, "unchanged": unchanged}[status].append(skill.name)

    expected = {skill.name for skill in skills}
    removed: list[str] = []
    if target.exists():
        for child in sorted(p for p in target.iterdir() if p.is_dir()):
            if child.name not in expected:
                removed.append(child.name)
                if clean and not dry_run:
                    shutil.rmtree(child)

    return ExportReport(
        source=str(source),
        target=str(target),
        dry_run=dry_run,
        clean=clean,
        skills_count=len(skills),
        copied=copied,
        updated=updated,
        unchanged=unchanged,
        removed=removed if clean else [],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="canonical packaged skills directory (default: %(default)s)",
    )
    parser.add_argument("--target", type=Path, required=True, help="runtime wrapper skills directory to write")
    parser.add_argument("--clean", action="store_true", help="remove target skill directories that are not in the source")
    parser.add_argument("--dry-run", action="store_true", help="report changes without writing files")
    parser.add_argument("--manifest", type=Path, help="optional JSON report path to write")
    args = parser.parse_args()

    report = export_skills(args.source, args.target, dry_run=args.dry_run, clean=args.clean)
    payload = asdict(report)
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.manifest:
        if not args.dry_run:
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
