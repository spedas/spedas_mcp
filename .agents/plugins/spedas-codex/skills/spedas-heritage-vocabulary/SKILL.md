---
name: spedas-heritage-vocabulary
description: Translate IDL SPEDAS, PySPEDAS, tplot, GUI plugin, and SPEDAS-J vocabulary into coherent Agent Kit skills/resources while marking external routines as not MCP tools.
---

# SPEDAS heritage vocabulary bridge

Use this skill when mining IDL SPEDAS, PySPEDAS, SPEDAS-J, GUI/plugin metadata, or legacy examples for Agent Kit content. It keeps heritage terminology useful without importing IDL implementation or telling MCP-only clients to call routines that are not Agent Kit tools.

## Boundary rule

Use the structured marker `external_runtime_route.not_an_mcp_tool: true` for examples or route objects. IDL `.pro` routines and PySPEDAS/PyTplot functions are source evidence or external runtime routes unless Agent Kit exposes a current MCP tool. Mark them as `not_an_mcp_tool` when writing skills. The Agent Kit user-facing path is: skill/resource guidance -> compact MCP planning/loading/geometry/cache tools -> artifact paths and provenance.

## Vocabulary map

| Heritage term | Agent Kit interpretation |
|---|---|
| IDL `tplot`, PyTplot `tplot` | Plotting/export workflow; backend writes figure artifacts, chat reports paths and compact stats. |
| IDL `STORE_DATA` / `GET_DATA`, PySPEDAS `store_data` / `get_data` | tplot variable lifecycle; inspect metadata/shape/coords/units before analysis. |
| `CDF`, `netCDF`, `tplot_save`, `tplot_restore`, ASCII export | Artifact formats; record paths, hashes, source products, and variable lists. |
| `spd_download`, CDAWeb, HAPI | Data-source routes; prefer Agent Kit discovery/planning/cache tools, with external PySPEDAS fallback labeled. |
| `cotrans`, `FAC`, `LMN`, `MVA`, `GSE/GSM/SM/GEO/J2000` | Coordinate/frame assumptions; route to existing geometry/rotation/LMN skills and cite provenance. |
| MMS/THEMIS/PSP/ERG loader names | Mission/product vocabulary; do not create one MCP tool per loader. Use skills/resources to choose products and bounded intervals. |
| GUI plugin `project`, `load_data`, `config`, `menu`, `data_processing`, `about` | Metadata schema for translating plugins into Agent Kit skills/resources: what it loads, options, menus/intents, processing steps, caveats. |
| SPEDAS-J / ERG / SuperDARN / IUGONET plugins | Domain source evidence and advanced external routes requiring human/domain review before first-class Agent Kit claims. |
| IDL-vs-PySPEDAS validation | Parity methodology and golden tests; actual validators belong in backend/CI artifacts. |

## Plugin-to-skill translation

When a SPEDAS plugin or example is considered for Agent Kit, extract this minimum metadata:

1. **Project/domain:** mission, instrument, ground network, model, or service.
2. **Load route:** preferred Agent Kit MCP route, or external PySPEDAS/IDL route marked `not_an_mcp_tool`.
3. **Options:** time range, probe/station, level/datatype, cadence, coordinates, support data, cache policy.
4. **Science intent:** what question this enables, and which existing skill should consume the output.
5. **Artifacts:** expected files/plots/tables and how to update `provenance/run.json`.
6. **Review owner:** whether this needs mission/domain expert review, IDL parity validation, or human approval.

## Compatibility and parity checklist

- Cite evidence paths or official docs; do not rely on routine names alone.
- Distinguish vocabulary translation from executable support.
- Prefer one composable skill over many thin loader-name skills.
- Preserve public names carefully: `spedas_agent_kit` is the product; older `spedas_mcp` names are historical unless kept as compatibility aliases.
- For IDL/PySPEDAS parity claims, record variable mappings, tolerances, time clipping, coordinate frame, units, and known archive/cache differences.
- For SPEDAS-J/ERG/IUGONET/SuperDARN content, mark maturity and domain-review caveats before surfacing to ordinary users.

## Do not do this

- Do not tell a naive MCP client to call `pyspedas.*`, `tplot_names`, `store_data`, `twavpol`, `neutral_sheet`, `cotrans`, `spd_download`, or an IDL `.pro` routine as if it were an Agent Kit MCP tool.
- Do not duplicate every IDL/PySPEDAS loader into Agent Kit. Use skills/resources to route intent; add backend support only when repeated workflows prove the generic surface inadequate.
- Do not import GUI/plugin code as a runtime dependency merely because its menu vocabulary is useful.
