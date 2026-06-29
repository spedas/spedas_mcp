# /spedas-agent-kit:analyze

Run a guided heliophysics **analysis** with the `spedas` MCP server by routing the user's intent to the right **skill** (each skill is an end-to-end procedure composing the unified data + analysis tools, with the scientific reliability checks baked in).

First call `spedas_overview()` if you need to check whether optional `[analysis]` tools are installed in this runtime, then load the `spedas-skills-index` skill (the intent → skill → first-tool router) and follow the matching skill. Available analysis skills:

| Intent | Skill |
|---|---|
| Turbulence / wave power spectrum of a field interval | `solar-wind-turbulence-spectrum` |
| Wave polarization (whistler/EMIC/chorus: degpol, wave-normal angle, ellipticity) | `wave-polarization` |
| Boundary normal / LMN frame from the data (MVA) | `boundary-minimum-variance` |
| Model (Shue) LMN boundary-normal frame | `model-lmn-boundary` |
| Full magnetopause/bow-shock crossing study (B + plasma + position) | `magnetopause-lmn-analysis` |
| Current density / gradients / magnetic nulls from a 4-spacecraft constellation | `multi-spacecraft-gradients` |
| Magnetotail neutral-sheet distance / side | `neutral-sheet-distance` |
| 2D velocity-space slice of a particle distribution (beams/crescents) | `particle-velocity-slice` |
| Apply a FAC/LMN rotation matrix to a vector series | `apply-rotation-matrix` |
| Clean/condition a messy series before analysis | `timeseries-cleaning` |
| Times two spacecraft/bodies are close (conjunction) | `spice-conjunction-finder` |
| Standard overview/summary plot + geomagnetic indices for a mission+date | `overview-geomagnetic-indices` |

All analysis skills are artifact-first; several plotting/transform/model steps require the optional `spedas-agent-kit[analysis]` extra, while data/geometry-only steps can still run without it: they bundle the run (`create_spedas_analysis_bundle`), write data/plots to disk, and return paths + compact stats. If no skill matches, fall back to `plan_spedas_observation` then the unified data layer.

User goal: $ARGUMENTS
