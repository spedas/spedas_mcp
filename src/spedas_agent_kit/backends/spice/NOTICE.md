# SPICE backend provenance and notice

This directory vendors the SPICE/ephemeris backend that was previously
distributed as `xhelio-spice`.

- Upstream/source package: `xhelio-spice`
- Source repository used for local verification: `huangzesen/xhelio-spice`
- Vendored into: `spedas_agent_kit.backends.spice`
- Upstream version declared in local source package: `0.6.0`
- Original author/copyright: Copyright (c) 2025 Zesen Huang
- License: MIT; see `LICENSE` in this directory.

The bundled JSON mission manifests under `manifests/` are derived from the same
`xhelio-spice` package and public NAIF/SPICE kernel archive metadata. Actual
SPICE kernels are intentionally not bundled; they are downloaded on demand into
the backward-compatible cache path (`~/.xhelio_spice/kernels/`) when a tool call
is allowed to fetch kernels.
