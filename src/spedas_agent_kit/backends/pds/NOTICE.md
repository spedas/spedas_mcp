# PDS backend provenance and notice

This directory vendors the PDS Planetary Plasma Interactions backend that was
previously distributed as `xhelio-pds`.

- Upstream/source package: `xhelio-pds`
- Source repository used for local verification: `huangzesen/xhelio-pds`
- Vendored into: `spedas_agent_kit.backends.pds`
- Original author/copyright: Copyright (c) 2026 Zesen Huang
- License: MIT; see `LICENSE` in this directory.

The upstream `xhelio-pds` local clone declares `license = "MIT"` in
`pyproject.toml` and does not contain a standalone license file. This vendored
copy carries the MIT notice explicitly so downstream source and wheel artifacts
retain a clear license/provenance trail.

The bundled JSON mission catalog and prompt seed files under `data/` are derived
from the same `xhelio-pds` package plus public NASA/PDS PPI registry metadata.
The larger regenerable metadata cache is intentionally not bundled; rebuild
helpers live under `scripts/`.
