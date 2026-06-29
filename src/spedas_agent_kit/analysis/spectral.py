"""Phase-2 time-frequency / wave-analysis tools (issue #15).

These functions implement the first two SPEDAS Agent Kit Phase-2 spectral tools:

- :func:`dynamic_power_spectrum` (#15) - sliding Hanning-window Welch dynamic
  power spectrum of a single scalar channel (``pyspedas`` ``dpwrspc``).
- :func:`wavelet_transform` (#15) - continuous wavelet transform (Morlet / Paul /
  DOG) of a single scalar channel via PyWavelets, with optional Torrence & Compo
  (1998) significance (``pyspedas`` ``idl_wavelet_scales`` / ``wave_signif``).

Design contract (mirrors :mod:`spedas_agent_kit.analysis.coords`, roadmap epic #5/#7):

- **File-in / file-out.** Inputs are paths to fetched CSV/JSON artifacts; the
  bulk ``time x frequency`` spectrogram matrix is written to ``output_dir`` as a
  compressed ``.npz``. Returns are small, JSON-serializable dicts with
  ``status``, the spectrogram path, and compact ranges/shape only. The full
  matrix is never returned inline (artifact-first discipline).
- **Lazy, gated backends.** ``pyspedas`` (and, for the wavelet tool,
  ``PyWavelets``) are imported only inside these functions; a missing
  ``[analysis]`` extra yields a clean ``status="error"`` payload. Significance
  computation and wide scale ranges are compute-heavy, so significance is gated
  behind an explicit ``compute_significance`` flag.
- **No network.** All computation is local; the tools never download data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import AnalysisDependencyError, require_pyspedas

# Continuous-wavelet families exposed by the wavelet tool. These map onto the
# PyWavelets continuous wavelets that pyspedas' wavelet() supports, plus the
# Torrence & Compo "mother" used for significance.
WAVELET_FAMILIES: dict[str, str] = {
    "morl": "MORLET",
    "paul": "PAUL",
    "gaus1": "DOG",
    "mexh": "DOG",
}


class AnalysisWaveletDependencyError(AnalysisDependencyError):
    """Raised when the PyWavelets backend (pulled in by pyspedas) is missing."""


def _error(
    message: str,
    *,
    code: str = "invalid_argument",
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the uniform structured error payload for analysis tools.

    Mirrors :func:`spedas_agent_kit.analysis.coords._error` and the server's
    ``_error_response`` envelope so spectral errors share the same
    ``{status: "error", code, message, ...}`` contract (issue #27).
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint is not None:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def _load_time_and_channel(
    input_file: str,
    data_col: str | None = None,
    time_col: str = "time",
) -> tuple[Any, Any, str]:
    """Read a time array (Unix seconds) and one scalar data channel from an artifact.

    Supports the CSV/JSON shapes written by the data-layer ``fetch_*`` tools as
    well as generic CSVs that carry an explicit time column plus numeric data
    columns. ``data_col`` selects the channel; if omitted, the first numeric
    non-time column is used.

    Returns ``(unix_time_ndarray, 1d_value_ndarray, resolved_data_column)``.

    Raises
    ------
    ValueError
        If the file cannot be parsed into a time array and a numeric channel.
    """
    import pandas as pd

    path = Path(input_file)
    if not path.exists():
        raise ValueError(f"input file does not exist: {input_file}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object mapping column -> list")
        df = pd.DataFrame(payload)
    else:
        df = pd.read_csv(path)

    if df.empty:
        raise ValueError("input file contains no rows")

    # Resolve the time column: prefer the named column, else fall back to the
    # first column (the data layer writes the DatetimeIndex as the first,
    # often "Unnamed: 0", column).
    if time_col in df.columns:
        time_series = df[time_col]
    elif len(df.columns) >= 1:
        time_series = df[df.columns[0]]
    else:
        raise ValueError(
            f"could not find time column '{time_col}'; available columns: {list(df.columns)}"
        )

    if pd.api.types.is_numeric_dtype(time_series):
        unix_time = time_series.to_numpy(dtype="float64")
    else:
        parsed = pd.to_datetime(time_series, utc=True, errors="coerce")
        if parsed.isna().all():
            raise ValueError("time column could not be parsed as numeric or datetime")
        unix_time = parsed.astype("int64").to_numpy() / 1e9

    # Resolve the scalar data channel.
    if data_col is None:
        candidate_cols = [
            c
            for c in df.columns
            if c != time_series.name and pd.api.types.is_numeric_dtype(df[c])
        ]
        if not candidate_cols:
            raise ValueError(
                "could not auto-detect a numeric data column; pass data_col explicitly. "
                f"columns found: {list(df.columns)}"
            )
        resolved = candidate_cols[0]
    else:
        if data_col not in df.columns:
            raise ValueError(
                f"data_col '{data_col}' not found in input; available: {list(df.columns)}"
            )
        if not pd.api.types.is_numeric_dtype(df[data_col]):
            raise ValueError(f"data_col '{data_col}' is not numeric")
        resolved = data_col

    values = df[resolved].to_numpy(dtype="float64")
    return unix_time, values, resolved


def _finite_range(array: Any) -> list[float] | None:
    """Return ``[min, max]`` over finite values, or ``None`` if none are finite."""
    import numpy as np

    arr = np.asarray(array, dtype="float64")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return [float(finite.min()), float(finite.max())]


def _sampling_interval(unix_time: Any, *, rtol: float = 0.01) -> tuple[float, str | None]:
    """Estimate the sampling interval ``dt`` (seconds) and flag irregular cadence.

    The spectral transforms assume a regular cadence: the wavelet scale grid and
    the resulting period/frequency axes are calibrated by a single ``dt``.  When
    the time axis is irregular, any single estimate (e.g. the first gap) mislabels
    the axes for the rest of the series with no outward sign.

    Returns ``(dt, warning)`` where ``dt`` is the **median** positive sample
    spacing (robust to a stray gap) and ``warning`` is ``None`` for a regular
    cadence or a human-readable string when the spacing varies by more than
    ``rtol`` of the median.
    """
    import numpy as np

    t = np.asarray(unix_time, dtype="float64")
    diffs = np.diff(t)
    finite = diffs[np.isfinite(diffs) & (diffs > 0)]
    if finite.size == 0:
        return float("nan"), None
    dt = float(np.median(finite))
    if dt <= 0:
        return dt, None
    spread = float(np.max(np.abs(finite - dt)))
    if spread > rtol * dt:
        return dt, (
            "time axis has an irregular cadence: sample spacing ranges "
            f"[{float(finite.min()):g}, {float(finite.max()):g}] s (median {dt:g} s). "
            "The wavelet period/frequency axes are calibrated to the median dt and "
            "will be inaccurate where the true cadence differs; resample to a "
            "uniform grid for reliable results."
        )
    return dt, None


def dynamic_power_spectrum(
    input_file: str,
    output_dir: str,
    data_col: str | None = None,
    nboxpoints: int = 256,
    nshiftpoints: int = 128,
    bin: int = 3,
    nohanning: bool = False,
    time_col: str = "time",
) -> dict[str, Any]:
    """Sliding-window Welch dynamic power spectrum of a scalar channel (#15).

    Backend: ``pyspedas.tplot_tools.tplot_math.dpwrspc.dpwrspc``. Reads a fetched
    CSV/JSON artifact, computes a dynamic power spectrum over the selected
    ``data_col``, writes the ``(time x frequency)`` power matrix (with its time
    and frequency axes) to ``output_dir/dynamic_power_spectrum.npz``, and returns
    paths plus compact ranges/shape only. Requires ``spedas-agent-kit[analysis]``.

    The spectrogram is intended to be paired with a downstream renderer; this
    tool never returns the bulk matrix inline.
    """
    if nboxpoints <= 0:
        return _error("nboxpoints must be a positive integer")
    if nshiftpoints <= 0:
        return _error("nshiftpoints must be a positive integer")
    if bin <= 0:
        return _error("bin must be a positive integer")

    try:
        require_pyspedas()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    try:
        import numpy as np

        unix_time, values, resolved = _load_time_and_channel(
            input_file, data_col=data_col, time_col=time_col
        )
    except ValueError as exc:
        return _error(str(exc))

    if values.shape[0] <= nboxpoints:
        return _error(
            "not enough samples for a dynamic power spectrum: "
            f"{values.shape[0]} points <= nboxpoints={nboxpoints}; "
            "reduce nboxpoints or supply a longer interval",
            code="invalid_argument",
            samples=int(values.shape[0]),
            nboxpoints=int(nboxpoints),
        )

    from pyspedas.tplot_tools.tplot_math.dpwrspc import dpwrspc

    tdps, fdps, dps = dpwrspc(
        unix_time,
        values,
        nboxpoints=int(nboxpoints),
        nshiftpoints=int(nshiftpoints),
        bin=int(bin),
        nohanning=bool(nohanning),
    )
    power = np.asarray(dps, dtype="float64")
    # dpwrspc signals "not enough points" by returning scalar -1 arrays.
    if power.ndim < 2 or power.size <= 1:
        return _error(
            "dpwrspc returned no spectrum; the interval is too short for the "
            "requested window. Reduce nboxpoints or supply more samples.",
            code="invalid_argument",
        )

    times = np.asarray(tdps, dtype="float64")
    freqs = np.asarray(fdps, dtype="float64")
    # pyspedas dpwrspc returns fdps as a time x frequency grid. Downstream
    # renderers expect a single frequency axis matching power.shape[1], so
    # collapse the grid deterministically before serializing the artifact.
    if freqs.ndim == 2:
        if freqs.shape[-1] == power.shape[-1]:
            freqs = freqs[0, :]
        elif freqs.shape[0] == power.shape[-1]:
            freqs = freqs[:, 0]
        else:
            freqs = freqs.reshape(-1)
    elif freqs.ndim > 2:
        freqs = np.squeeze(freqs)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spectrogram_path = out_dir / "dynamic_power_spectrum.npz"
    np.savez_compressed(
        spectrogram_path,
        time=times,
        freq=freqs,
        power=power,
    )

    return {
        "status": "success",
        "tool": "dynamic_power_spectrum",
        "spectrogram_file": str(spectrogram_path),
        "data_col": resolved,
        "shape": list(power.shape),
        "time_range": _finite_range(times),
        "freq_range": _finite_range(freqs),
        "nboxpoints": int(nboxpoints),
        "nshiftpoints": int(nshiftpoints),
        "bin": int(bin),
        "hanning": not bool(nohanning),
        "note": (
            "Power matrix saved as (n_time, n_freq) in the .npz under key 'power' "
            "with axes 'time' (Unix seconds) and 'freq' (1/time units). Pair with a "
            "renderer to view; this tool returns ranges/shape only."
        ),
    }


def wavelet_transform(
    input_file: str,
    output_dir: str,
    data_col: str | None = None,
    wavename: str = "morl",
    min_period: float | None = None,
    max_period: float | None = None,
    compute_significance: bool = False,
    siglvl: float = 0.95,
    time_col: str = "time",
) -> dict[str, Any]:
    """Continuous wavelet transform of a scalar channel (#15).

    Backend: PyWavelets ``cwt`` over scales derived from
    ``pyspedas.analysis.wavelet.idl_wavelet_scales`` (Torrence & Compo scale
    grid), optionally filtered to ``[min_period, max_period]``. When
    ``compute_significance`` is set, the per-scale 95% red-noise significance
    (``pyspedas.analysis.wave_signif.wave_signif``) is broadcast against the
    power so a downstream renderer can contour the significant region.

    Writes the ``(time x frequency)`` power matrix (plus frequency/period axes and
    optional significance) to ``output_dir/wavelet_transform.npz`` and returns
    paths plus compact ranges/shape only. Requires ``spedas-agent-kit[analysis]``.
    """
    wave_key = (wavename or "").strip().lower()
    # Accept the documented short names plus any cmorB-C / gausP style name that
    # PyWavelets itself understands; gate significance on a known mother only.
    mother = WAVELET_FAMILIES.get(wave_key)
    if mother is None and wave_key not in WAVELET_FAMILIES and not wave_key:
        return _error(
            f"unsupported wavename '{wavename}'",
            supported_wavelets=sorted(WAVELET_FAMILIES),
        )
    if min_period is not None and max_period is not None and min_period >= max_period:
        return _error(
            f"min_period ({min_period}) must be < max_period ({max_period})"
        )
    if not (0.0 < siglvl < 1.0):
        return _error("siglvl must be between 0 and 1 (exclusive)")

    try:
        require_pyspedas()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    try:
        import pywt  # noqa: F401  (PyWavelets, pulled in by the analysis extra)
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch
        return _error(
            "This tool requires PyWavelets (installed with the analysis extra). "
            "Install it with: pip install 'spedas-agent-kit[analysis]'. "
            f"(import error: {exc})",
            code="dependency_missing",
        )

    try:
        import numpy as np

        unix_time, values, resolved = _load_time_and_channel(
            input_file, data_col=data_col, time_col=time_col
        )
    except ValueError as exc:
        return _error(str(exc))

    finite_values = np.isfinite(values)
    finite_count = int(finite_values.sum())
    min_finite_samples = 2
    if values.shape[0] < min_finite_samples or finite_count < min_finite_samples:
        return _error(
            f"data column '{resolved}' has {finite_count} finite samples out of "
            f"{int(values.shape[0])}; wavelet transform needs at least "
            f"{min_finite_samples} finite numeric samples",
            code="invalid_argument",
            data_col=resolved,
            finite_samples=finite_count,
            total_samples=int(values.shape[0]),
            min_finite_samples=min_finite_samples,
            hint=(
                "Supply a non-empty numeric data column or select a longer interval "
                "before running wavelet_transform."
            ),
        )

    from pyspedas.analysis.wavelet import idl_wavelet_scales

    dt, cadence_warning = _sampling_interval(unix_time)
    if not np.isfinite(dt) or dt <= 0:
        return _error(
            "could not determine a positive sampling interval from the time axis; "
            "ensure the input is time-ordered with a regular cadence"
        )

    try:
        # ``idl_wavelet_scales`` scales with the supplied cadence.  PyWavelets
        # ``cwt`` expects dimensionless scales in sample units, so build the
        # Torrence-Compo grid at ``dt=1`` for the transform itself and apply the
        # physical cadence only to the returned period/frequency axes.  Passing
        # second-valued scales directly to PyWavelets rejects otherwise-valid
        # sub-minute cadence data with "Selected scale ... too small" (#82).
        scales, _freqs0, periods0 = idl_wavelet_scales(values.shape[0], 1.0)
    except ValueError as exc:
        return _error(str(exc))
    scales = np.asarray(scales, dtype="float64")
    periods0 = np.asarray(periods0, dtype="float64") * dt

    # Restrict the scale grid to the requested period band before the (heavy)
    # CWT so we never compute scales the caller will discard.
    keep = np.ones(scales.shape[0], dtype=bool)
    if min_period is not None:
        keep &= periods0 >= float(min_period)
    if max_period is not None:
        keep &= periods0 <= float(max_period)
    if not keep.any():
        return _error(
            "no wavelet scales fall within the requested period band "
            f"[{min_period}, {max_period}]; the natural band is "
            f"[{float(periods0.min())}, {float(periods0.max())}] s",
            code="invalid_argument",
            natural_period_range=[float(periods0.min()), float(periods0.max())],
        )
    scales = scales[keep]
    periods0 = periods0[keep]

    coef, freqs = pywt.cwt(
        values,
        scales=scales,
        wavelet=wavename,
        method="fft",
        sampling_period=dt,
    )
    power = (np.abs(np.asarray(coef, dtype="float64")) ** 2).transpose()  # (n_time, n_scale)
    # Keep the returned axes calibrated to the actual PyWavelets wavelet family.
    # ``periods0`` above is the Torrence-Compo/Morlet period grid used for
    # SPEDAS-style period-band filtering; PyWavelets returns wavelet-specific
    # frequencies after applying ``sampling_period=dt``.
    freqs = np.asarray(freqs, dtype="float64")
    periods = np.where(freqs != 0, 1.0 / freqs, np.nan)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spectrogram_path = out_dir / "wavelet_transform.npz"
    save_kwargs: dict[str, Any] = {
        "time": unix_time,
        "freq": freqs,
        "period": periods,
        "power": power,
    }

    significance_applied = False
    if compute_significance:
        if mother is None:
            return _error(
                f"significance is only supported for known mothers "
                f"{sorted(WAVELET_FAMILIES)}; got wavename '{wavename}'",
                code="invalid_argument",
            )
        from pyspedas.analysis.wave_signif import wave_signif

        # ``wave_signif`` follows the Torrence-Compo convention where scales
        # carry the same physical units as ``dt``.
        significance_scales = scales * dt
        signif, _outputs = wave_signif(
            values, dt, significance_scales, 0, siglvl=siglvl, mother=mother
        )
        signif = np.asarray(signif, dtype="float64")
        save_kwargs["significance"] = signif
        significance_applied = True

    np.savez_compressed(spectrogram_path, **save_kwargs)

    return {
        "status": "success",
        "tool": "wavelet_transform",
        "spectrogram_file": str(spectrogram_path),
        "data_col": resolved,
        "wavename": wavename,
        "shape": list(power.shape),
        "time_range": _finite_range(unix_time),
        "freq_range": _finite_range(freqs),
        "period_range": _finite_range(periods),
        "significance_computed": significance_applied,
        "siglvl": float(siglvl) if significance_applied else None,
        "sampling_interval_s": float(dt),
        "cadence_warning": cadence_warning,
        "note": (
            "Power matrix saved as (n_time, n_freq) in the .npz under key 'power' "
            "with axes 'time' (Unix seconds), 'freq' (Hz), and 'period' (s)"
            + (", plus per-scale 'significance'." if significance_applied else ".")
            + " Pair with a renderer to view; this tool returns ranges/shape only."
        ),
    }


__all__ = [
    "WAVELET_FAMILIES",
    "dynamic_power_spectrum",
    "wavelet_transform",
]
