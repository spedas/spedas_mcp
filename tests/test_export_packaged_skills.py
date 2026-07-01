import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_packaged_skills.py"
SOURCE = ROOT / "src" / "spedas_agent_kit" / "resources" / "skills"


def _run_export(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, args)],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_export_packaged_skills_materializes_canonical_skill_set(tmp_path):
    target = tmp_path / "runtime-plugin" / "skills"
    manifest = tmp_path / "manifest.json"

    result = _run_export("--target", target, "--manifest", manifest)
    payload = json.loads(result.stdout)

    assert payload["skills_count"] >= 22
    assert "spedas-workflow" in payload["copied"]
    assert (target / "spedas-workflow" / "SKILL.md").read_text(encoding="utf-8") == (
        SOURCE / "spedas-workflow" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert json.loads(manifest.read_text(encoding="utf-8")) == payload

    second = json.loads(_run_export("--target", target).stdout)
    assert second["copied"] == []
    assert second["updated"] == []
    assert "spedas-workflow" in second["unchanged"]


def test_export_packaged_skills_clean_and_dry_run_reports_extra_dirs(tmp_path):
    target = tmp_path / "skills"
    _run_export("--target", target)
    extra = target / "local-extra-skill"
    extra.mkdir()
    (extra / "SKILL.md").write_text("---\nname: local-extra-skill\ndescription: extra\n---\n", encoding="utf-8")

    dry = json.loads(_run_export("--target", target, "--clean", "--dry-run").stdout)
    assert "local-extra-skill" in dry["removed"]
    assert extra.exists()

    clean = json.loads(_run_export("--target", target, "--clean").stdout)
    assert "local-extra-skill" in clean["removed"]
    assert not extra.exists()
