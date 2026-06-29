# CDAWeb backend provenance and notice

This directory vendors the CDAWeb backend that was previously distributed as
`xhelio-cdaweb`.

- Upstream/source package: `xhelio-cdaweb`
- Source repository used for local verification: `huangzesen/xhelio-cdaweb`
- Vendored into: `spedas_agent_kit.backends.cdaweb`
- Original author/copyright: Copyright (c) 2026 Zesen Huang
- License: MIT; see `LICENSE` in this directory.

The bundled JSON catalog and prompt seed files under `data/` are derived from the
same `xhelio-cdaweb` package plus public CDAWeb/NASA metadata endpoints. The
large regenerable metadata cache is intentionally not bundled; rebuild helpers
live under `scripts/`.
