# Example: agent workflow with SPEDAS Agent Kit data layer

This example is intentionally tool-oriented rather than tied to one agent runtime. Claude Code, Codex, OpenCode, LingTai, or another MCP-capable client can follow the same sequence.

## Open-ended science request

> Plan a Juno magnetic-field and geometry study near Jupiter for a selected interval.

Recommended sequence:

1. Start with the science workflow layer:

   ```text
   search_spedas_data_sources(
     question="Study Juno magnetic field measurements near Jupiter and add spacecraft geometry context",
     target="Jupiter",
     observables=["magnetic field", "spacecraft position"]
   )
   ```

   Expected result: `pds` and `spice` should rank high, because PDS can provide archived Juno field products while SPICE provides geometry/trajectory context.

2. Create a plan:

   ```text
   plan_spedas_observation(
     science_goal="Plan a Juno magnetic field and geometry study",
     target="Jupiter",
     start="YYYY-MM-DDTHH:MM:SSZ",
     stop="YYYY-MM-DDTHH:MM:SSZ",
     data_sources=["pds", "spice"]
   )
   ```

3. Browse the unified data layer:

   ```text
   browse_data_sources(source_type="all")
   browse_data_sources(source_type="pds", query="juno")
   browse_data_sources(source_type="spice")
   ```

4. Load source context and browse parameters/frames:

   ```text
   load_data_source(source_type="pds", source_id="JUNO_PPI")
   browse_data_parameters(source_type="pds", dataset_id="...")
   load_data_source(source_type="spice", source_id="JUNO")
   browse_data_parameters(source_type="spice", dataset_id="JUNO")
   ```

5. Scaffold a provenance bundle before fetching:

   ```text
   create_spedas_analysis_bundle(
     study_name="juno-jupiter-field-geometry",
     output_dir="./runs",
     science_goal="Plan a Juno magnetic field and geometry study",
     target="Jupiter",
     data_sources=["pds", "spice"]
   )
   ```

6. Fetch/compute only after the mission, dataset, parameters, frames, and time range are explicit:

   ```text
   fetch_data_product(
     source_type="pds",
     dataset_id="...",
     parameters=["..."],
     start="YYYY-MM-DDTHH:MM:SSZ",
     stop="YYYY-MM-DDTHH:MM:SSZ",
     output_dir="./runs/juno-jupiter-field-geometry/data"
   )

   get_ephemeris(...)
   compute_distance(...)
   ```

7. Return compact summaries and paths to generated artifacts. Do not paste large data arrays into chat.

## Mixed heliophysics request

> Compare solar wind plasma and spacecraft geometry during an Earth bow-shock interval.

Likely source categories:

- `cdaweb` for OMNI/MMS/THEMIS/other time-series measurements.
- `spice` for geometry, frames, and distance/position context when applicable.

Recommended first calls:

```text
search_spedas_data_sources(
  question="Compare solar wind plasma and spacecraft geometry during an Earth bow shock interval",
  target="Earth bow shock",
  observables=["plasma", "magnetic field", "position"]
)

plan_spedas_observation(
  science_goal="Compare solar wind plasma and spacecraft geometry during an Earth bow shock interval",
  target="Earth bow shock",
  start="YYYY-MM-DDTHH:MM:SSZ",
  stop="YYYY-MM-DDTHH:MM:SSZ"
)
```

Then continue through the data layer:

```text
browse_data_sources(source_type="cdaweb")
load_data_source(source_type="cdaweb", source_id="...")
browse_data_parameters(source_type="cdaweb", dataset_id="...")
fetch_data_product(source_type="cdaweb", dataset_id="...", parameters=["..."], start="...", stop="...", output_dir="./runs/.../data")
```

Use direct geometry tools when SPICE context is required.
