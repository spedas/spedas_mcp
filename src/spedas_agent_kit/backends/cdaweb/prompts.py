"""Prompt assembly — builds observatory catalog text for load_observatory."""

from pathlib import Path

from spedas_agent_kit.backends.cdaweb.catalog import load_observatory_json, observatory_to_markdown
from spedas_agent_kit.backends.cdaweb.config import get_cache_root

# Prompt templates are static and stay bundled with the package
_BUNDLED_PROMPTS = Path(__file__).parent / "data" / "prompts"


def _load_prompt_template(filename: str) -> str:
    """Load a prompt template from the bundled package data."""
    filepath = _BUNDLED_PROMPTS / filename
    if not filepath.exists():
        return ""
    return filepath.read_text(encoding="utf-8").strip()


def build_observatory_prompt(observatory_stem: str) -> str:
    """Build the complete catalog text for an observatory.

    Assembles:
    1. Usage instructions (how to use browse_parameters / fetch_data)
    2. CDAWeb-specific workflow instructions
    3. Observatory profile + full dataset catalog as markdown

    Args:
        observatory_stem: Lowercase observatory identifier (e.g., 'ace', 'psp').

    Returns:
        Formatted text with observatory catalog and usage instructions.

    Raises:
        FileNotFoundError: If no observatory JSON exists.
    """
    # Usage instructions
    generic_role = _load_prompt_template("generic_role.md")

    # CDAWeb workflow
    cdaweb_role = _load_prompt_template("cdaweb_role.md")

    # Observatory data
    observatory = load_observatory_json(observatory_stem)
    profile = observatory.get("profile", {})

    # Observatory overview
    overview_lines = []
    name = observatory.get("name", observatory_stem.upper())
    overview_lines.append(f"## Observatory: {name}")
    if profile.get("description"):
        overview_lines.append(profile["description"])
    coords = profile.get("coordinate_systems", [])
    if coords:
        overview_lines.append(f"- Coordinate system(s): {', '.join(coords)}")
    cadence = profile.get("typical_cadence")
    if cadence:
        overview_lines.append(f"- Typical cadence: {cadence}")
    if profile.get("data_caveats"):
        overview_lines.append("- Data caveats: " + "; ".join(profile["data_caveats"]))
    overview_lines.append("")
    observatory_overview = "\n".join(overview_lines)

    # Dataset catalog
    dataset_catalog = observatory_to_markdown(observatory)

    # Cache paths
    root = get_cache_root()
    cache_info = "\n".join([
        "## Cache Locations",
        "",
        f"- Observatory catalogs (JSON): `{root / 'observatories'}/`",
        f"- Parameter metadata (JSON): `{root / 'metadata'}/`",
        f"- Downloaded CDF files: `{root / 'cdf'}/`",
    ])

    # Assemble
    parts = [p for p in [generic_role, cdaweb_role, cache_info, observatory_overview, dataset_catalog] if p]
    return "\n\n".join(parts)
