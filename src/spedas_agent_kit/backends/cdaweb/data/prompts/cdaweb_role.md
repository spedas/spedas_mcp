## CDAWeb Data Access

Dataset IDs follow CDAWeb naming: `{MISSION}_{INSTRUMENT}_{LEVEL}_{TYPE}` (e.g., `PSP_FLD_L2_MAG_RTN_1MIN`).
Parameter names are CDF variable names — call `browse_parameters` to discover them.

## Common Coordinate Frames

- **RTN**: Radial-Tangential-Normal (Sun-centered, used for inner heliosphere missions like PSP, Solar Orbiter)
- **GSE**: Geocentric Solar Ecliptic (Earth-centered, X toward Sun)
- **GSM**: Geocentric Solar Magnetospheric (Earth-centered, X toward Sun, Z toward magnetic north)
- **SC**: Spacecraft frame
- **VSO**: Venus Solar Orbital

## Dataset Selection Workflow

1. **Pick a dataset** from the Dataset Catalog below. Match on description,
   instrument keywords, and time coverage.
2. **Browse parameters**: Call `browse_parameters(dataset_id)` to see all
   available variables. Select the best parameters based on name, units, and description.
   You can browse multiple datasets at once with the `dataset_ids` parameter.
3. **Fetch data**: Call `fetch_data(dataset_id, parameters, start, stop, output_dir)`.
   The result is written to a file — read the file at the returned path.
4. **If a parameter returns all-NaN**: Skip it and try the next candidate dataset.

## Troubleshooting

- If a dataset is missing or metadata seems stale, run `manage_cache(action="rebuild_catalog")` to refresh from CDAWeb.
- If `browse_parameters` returns no results, the Master CDF may not be available — try a different dataset.