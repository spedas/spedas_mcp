# /spedas-agent-kit:spice

Use the `spedas` MCP server for SPICE ephemeris, distance, or coordinate-frame work.

1. Start with `spedas_overview()` and `manage_data_cache(source_type="spice", action="status")` to confirm the unified SPICE/geometry surface. The older separate mission/frame listing tools are not part of the current base surface.
   SPICE support is target/kernel dependent. MMS and Cluster do **not** have current in-tree SPICE backend kernels here; for their geometry use the CDAWeb data layer (e.g. `load_data_source(source_type="cdaweb", source_id="mms")`), not `get_ephemeris`.
   An unsupported target returns a structured `unsupported_spice_target` error
   with alternatives.
2. Use `get_ephemeris(target=..., time=..., time_end=..., output_file=...)`, `compute_distance`, or `transform_coordinates` as appropriate. For a single state, omit `time_end`; for a trajectory, provide both `time_end` and `output_file`.
3. For time series, require an `output_file` and keep intervals small unless the user asked otherwise.
4. Kernel downloads are gated. If the required SPICE kernels are not already
   cached, these tools return a `needs_confirmation` /`kernel_download_required`
   response instead of silently downloading 100 MB–1 GB of kernels (PSP ~266 MB).
   To proceed, either load the mission explicitly with
   `manage_data_cache(source_type="spice", action="load", mission=...)` (preview first with
   `action="check_remote"`), or re-call the tool with `allow_kernel_download=True`.
   Mention the download size/cache cost to the user before opting in.

Task: $ARGUMENTS
