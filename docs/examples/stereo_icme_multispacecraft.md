# STEREO / Wind / ACE heliospheric ICME and SEP workflow

Use this example for first-pass paper reproductions where the science question
combines STEREO, Wind, ACE, OMNI, or STEREO energetic-particle context. It is a
reduced in-situ workflow, not a full heliospheric-imaging or paper-boundary
solver.

## Batch 007 seed events

| Iteration | Paper / event family | DOI / metadata status | Starting interval | First-pass route | Quality label |
|---|---|---|---|---|---|
| 031 | Liu et al. STEREO ICME case | `10.5194/angeo-27-4491-2009` | `2007-05-19/00:00:00`–`2007-05-23/00:00:00` | STEREO-A/B MAG `1min` + PLASTIC proton moments; Wind/ACE/OMNI optional context | `proxy` |
| 032 | Möstl et al. STEREO/Wind magnetic cloud and shock-sheath | `10.1007/s11207-009-9360-7` | `2007-05-20/00:00:00`–`2007-05-24/00:00:00` | STEREO-A/B MAG + PLASTIC, Wind MFI/SWE or OMNI comparison | `proxy` |
| 033 | Lepping/Berdichevsky Bastille Day magnetic cloud | `10.1029/2001GL014136` | `2000-07-14/00:00:00`–`2000-07-17/00:00:00` | Wind MFI/SWE + ACE MAG/SWEPAM + OMNI geomagnetic indices | `proxy` |
| 034 | Dresing et al. 17 Jan 2010 SEP longitudinal spread | `10.1007/s11207-012-0049-y` | `2010-01-17/00:00:00`–`2010-01-19/00:00:00` | STEREO SEPT reduced-intensity proxies + STEREO MAG context; ACE/Wind only if channel metadata are verified | `reduced_sep_proxy` |
| 035 | Lugaz/Temmer August 2010 CME-CME interaction family | exact Lugaz DOI unresolved in Batch 007 | `2010-08-01/00:00:00`–`2010-08-06/00:00:00` | STEREO MAG/PLASTIC + OMNI/Wind/ACE in-situ context | `proxy, metadata_unresolved` |

Treat these as event/paper seeds, not API presets. Promote them only after the
paper interval, instrument products, coordinate basis, and boundary/onset
methods match the target paper.

## First-pass workflow

1. **Plan the route before fetching.** Use `spedas_overview()` and
   `plan_spedas_observation()` to identify whether the event is source-spacecraft
   (Wind/ACE), propagated near-Earth (OMNI), or heliospheric (STEREO-A/B).
2. **Start at low cadence.** For multi-day STEREO intervals, start with MAG
   `1min` plus PLASTIC proton moments. Escalate to high-rate MAG only after a
   narrow boundary sub-interval is known.
3. **Normalize spacecraft-specific aliases.** Record whether STEREO MAG exposes
   `BFIELD` or component variables, and record PLASTIC aliases such as
   `proton_bulk_speed`, `proton_number_density`, and `proton_temperature`.
4. **Build a standard overview.** Plot `|B|` or components, speed, density,
   temperature, and optional OMNI `SYM_H`/AE indices for near-Earth response.
5. **Label boundary and timing status.** Mark shock/sheath/cloud boundaries as
   `not_identified`, `event_list_boundaries`, or `paper_boundaries`; do not imply
   automatic boundary finding from an overview plot.
6. **Handle SEP products as reduced proxies.** For STEREO SEPT/LET/HET or
   ACE/Wind particle channels, record telescope, species, energy band, units, and
   channel metadata before comparing onsets. Without that metadata, a profile is
   only a `reduced_sep_proxy`, not a calibrated onset/fluence/anisotropy result.
7. **State the remote-sensing boundary.** SECCHI/HI J-maps, CME triangulation,
   and arrival-time model fitting are outside this reduced in-situ workflow unless
   those products are explicitly loaded and documented.

## Report caveat template

> This artifact is a proxy reproduction of the in-situ data route and timing
> context. It does not claim paper-quality shock/sheath/cloud boundaries,
> calibrated SEP onset/fluence, or HI/J-map reproduction. Boundary markers,
> energy-channel choices, and CME-arrival model assumptions remain explicit
> follow-up work.

## Minimal provenance additions

```json
{
  "heliospheric_icme_sep": {
    "event_role": "stereo_icme | magnetic_cloud | sep_spread | cme_cme_interaction",
    "primary_sources": ["STEREO-A MAG", "STEREO-B PLASTIC", "Wind MFI", "OMNI"],
    "cadence_choice": "1min first | high_rate_subinterval",
    "boundary_status": "not_identified | event_list_boundaries | paper_boundaries",
    "sep_status": "not_used | reduced_sep_proxy | calibrated_channels",
    "remote_sensing_status": "not_attempted | caveated_context | reproduced",
    "quality": "proxy | reduced_sep_proxy | metadata_unresolved | paper_quality"
  }
}
```

## Agent Kit feedback pattern

> Agent Kit feedback: multi-spacecraft ICME and SEP reproductions need a named
> low-cadence STEREO/Wind/ACE/OMNI overview recipe, event seed table, explicit
> SEP energy-channel metadata guardrails, and an in-band HI/J-map boundary caveat.
> Evidence: Batch 007 reproductions 031–035 required manual route selection,
> spacecraft alias normalization, and proxy labels even though the underlying
> STEREO/PLASTIC/SEPT routes already existed.
