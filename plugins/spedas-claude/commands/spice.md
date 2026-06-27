# /spedas-mcp:spice

Use the `spedas` MCP server for SPICE ephemeris, distance, or coordinate-frame work.

1. Start with `list_spice_missions()` and, if needed, `list_coordinate_frames()`.
   Only the missions listed there have SPICE kernels. MMS and Cluster do **not** —
   for their geometry use the CDAWeb data layer (e.g.
   `load_data_source(source_type="cdaweb", source_id="mms")`), not `get_ephemeris`.
   An unsupported target returns a structured `unsupported_spice_target` error
   with alternatives.
2. Use `get_ephemeris`, `compute_distance`, or `transform_coordinates` as appropriate.
3. For time series, require an `output_file` and keep intervals small unless the user asked otherwise.
4. Kernel downloads are gated. If the required SPICE kernels are not already
   cached, these tools return a `needs_confirmation` /`kernel_download_required`
   response instead of silently downloading 100 MB–1 GB of kernels (PSP ~266 MB).
   To proceed, either load the mission explicitly with
   `manage_spice_kernels(action="load", mission=...)` (preview first with
   `action="check_remote"`), or re-call the tool with `allow_kernel_download=True`.
   Mention the download size/cache cost to the user before opting in.

Task: $ARGUMENTS
