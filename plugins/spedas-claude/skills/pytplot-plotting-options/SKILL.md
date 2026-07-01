---
name: pytplot-plotting-options
description: Choose artifact-first PyTplot/SPEDAS plotting options for line plots, spectrograms, limits, legends, markers, annotations, and saved figure outputs without expanding the default Agent Kit MCP tool surface.
---

# PyTplot plotting options

Use this skill when a request mentions PyTplot, `tplot`, IDL SPEDAS plot
options, spectrogram styling, y/z limits, log axes, labels, legends, event bars,
plot highlights, saved PNG/SVG/PDF figures, or "make this SPEDAS plot look like
...". It complements `tplot-data-lifecycle`: first make variable state and
metadata explicit, then use this skill to decide the plot option manifest and
artifact output.

## MCP/default-surface boundary

This skill adds no MCP tool. PySPEDAS/PyTplot plotting calls are source evidence
or external runtime routes and must be marked with the structured marker
`external_runtime_route.not_an_mcp_tool: true` unless a current Agent Kit tool
explicitly exposes the action.

```yaml
external_runtime_route:
  not_an_mcp_tool: true
  examples:
    - pyspedas.options
    - pyspedas.tplot_options
    - pyspedas.tplot
    - pyspedas.ylim
    - pyspedas.zlim
    - pyspedas.xlim
    - pyspedas.tlimit
    - pyspedas.timebar
    - pyspedas.databar
    - pyspedas.tplot_tools.MPLPlotter.highlight
    - pyspedas.tplot_tools.MPLPlotter.annotate
```

Do **not** tell an MCP-only client to call invented MCP-prefixed PySPEDAS
option or plotting tools, and do not present `pyspedas.tplot` as a dedicated
Agent Kit tool. The Agent Kit path is: choose the variables and plot semantics
-> create/update the run bundle -> let the backend/[analysis] route such as
`render_tplot` (when enabled) or a runtime PySPEDAS script write figure
artifacts -> return paths, hashes, `plot_options.json`, and
`provenance/run.json` entries.

## Recipe model

1. **Start from variable metadata.** Load `tplot-data-lifecycle` first if variable
   names, dimensions, units, coordinate frames, cadence, support-data flags, or
   fill/interpolation status are unclear. Do not paste arrays.
2. **Choose plot family.** A scalar/vector time series is a line/panel plot; an
   energy/frequency/pitch-angle product is usually a spectrogram; a pseudo-var
   panel may combine multiple variables. Record this decision in a plot manifest.
3. **Separate global from per-variable options.** Use global options for the
   figure/window/time context; use per-variable options for panel semantics.
4. **Save an artifact, not an interactive window.** In headless Agent Kit runs,
   prefer saved files (`save_png`, `save_svg`, `save_pdf`, or `save_jpeg`) with
   `display=False`. Return the file path and a compact option summary.
5. **Record interpretation-changing choices.** Log axes, clipping versus display
   limits, z ranges, color maps, event bars, annotations, and any plot-time data
   gap handling belong in `provenance/run.json` and a sidecar such as
   `plot_options.json`.

## Option map

| Intent | PySPEDAS/PyTplot evidence (`not_an_mcp_tool`) | Agent Kit plot-manifest field |
|---|---|---|
| Whole-figure title, style, axis font, size, x range, annotations, compact variable-label layout | `pyspedas.tplot_options('title', ...)`, `title_size`, `style`, `axis_font_size`, `xsize`, `ysize`, `x_range`, `annotations`, `varlabel_style` | `global_options` |
| Per-panel labels, units, y range, log y, visibility, panel sizing | `pyspedas.options(name, 'ytitle', ...)`, `ysubtitle`, `yrange` / `y_range`, `ylog`, `visible`, `nodata`, `panel_size` | `panels[*].yaxis`, `panels[*].labels` |
| Spectrogram / energy-frequency-pitch plots | `pyspedas.options(name, 'spec', True)`, `colormap`, `zrange` / `z_range`, `zlog`, `ztitle`, `zsubtitle`, `spec_dim_to_plot`, `spec_slices_to_use`, `x_interp`, `y_interp` | `panels[*].spectrogram` |
| Legend and trace naming | `legend_names`, `legend_location`, `legend_size`, `legend_ncols`, `legend_markerfirst`, `legend_linewidth` | `panels[*].legend` |
| Trace style and markers | `line_color` / `color`, `line_style` / `linestyle`, `line_width` / `thick`, `marker`, `marker_size` / `markersize`, `markevery`, `symbols` | `panels[*].traces` |
| Error bars or uncertainty overlays | `errorevery`, `capsize`, `ecolor`, `elinewidth` | `panels[*].error_bars` |
| Event bars, horizontal data bars, highlights, text callouts | `pyspedas.timebar(...)`, `pyspedas.databar(...)`, `highlight(...)`, `annotate(...)` | `annotations`, `event_marks` |
| Time and axis limits | `pyspedas.xlim(...)`, `pyspedas.tlimit([...])`, `pyspedas.ylim(name, min, max, logflag)`, `pyspedas.zlim(name, min, max, logflag)` | `global_options.x_range`, `panels[*].yaxis`, `panels[*].spectrogram.zaxis` |

## Line-plot checklist

- Confirm variable names, component labels, units, coordinate frame, and cadence.
- Set `ytitle`/`ysubtitle` from science quantity and units, not just loader names.
- Use `legend_names` for vector components (`Bx`, `By`, `Bz`, `|B|`) and note frame
  (`GSE`, `GSM`, `RTN`, `FAC`, `LMN`) in the label or caption.
- Use `yrange`/`y_range` and `ylog` only when the scientific reason is clear; do
  not hide outliers without recording the display range.
- For markers/error bars, record marker cadence (`markevery`) and uncertainty
  source (`errorevery`, `capsize`, `ecolor`, `elinewidth`).

## Spectrogram checklist

- Verify the independent axis and units before setting `spec=True`: energy,
  frequency, pitch angle, or another bin variable.
- Use `zlog` and `zrange`/`z_range` deliberately; record the colorbar units in
  `ztitle`/`zsubtitle`.
- For multidimensional products, name `spec_dim_to_plot` and `spec_slices_to_use`
  instead of silently summing or slicing dimensions.
- Prefer `colormap` choices that make scientific contrast visible and record the
  chosen map in the artifact caption.
- For particle products, hand off product/calibration caveats to
  `particle-velocity-slice`, `pitch-angle-distribution`, or mission skills before
  interpreting beams, crescents, loss cones, or pitch-angle anisotropy.

## Event annotation checklist

- Use `timebar` / `databar`, `highlight`, and `annotate` as external runtime route
  vocabulary, not Agent Kit MCP tools.
- Tie event marks to a source: paper interval, event-preset resource, automated
  threshold, manual inspection, or mission operations note.
- Preserve exact event times, colors, labels, and whether the mark is vertical
  time, horizontal data threshold, shaded interval, or text annotation.

## Artifact/provenance contract

Every nontrivial plot request should leave a bundle record that includes:

- figure artifacts: PNG/SVG/PDF/JPEG paths, size, SHA-256 when available;
- `plot_options.json`: variables, global options, per-panel options, spectrogram
  options, annotations/event marks, and output formats;
- `provenance/run.json`: data sources, time range, load clipping, variable names,
  coordinate frames, units, display-only limits, log scales, gap/fill handling,
  and caveats;
- a compact response: paths plus key interpretation options. Do not paste arrays,
  full CDF contents, or image binaries in chat.

## Handoffs

- `pyspedas-load-planning` for bounded load/cache/no-update choices before plotting.
- `tplot-data-lifecycle` for variable state, metadata, naming, export, and cleanup.
- `coordinate-transform-recipes` when plot labels or legends depend on frame
  transforms (`GSE`, `GSM`, `RTN`, `FAC`, `LMN`).
- `wave-polarization`, `power-spectral-density`, or `spectral-cross-coherence`
  for spectra/wave-science interpretation after the figure is well defined.
- Mission workflow skills (`themis-workflows`, `mms-basic-workflows`,
  `psp-solo-heliophysics-workflows`, `omni-kyoto-noaa-smoke-workflows`) for
  product-specific caveats and source choices.
