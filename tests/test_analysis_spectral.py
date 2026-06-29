"""Offline tests for the Phase-2 spectral / wave-analysis tools (issue #15).

Like ``test_analysis_coords.py``, these run without network access and without a
real ``pyspedas`` / ``PyWavelets`` install:

- Argument validation happens before the backend import and is checked directly.
- The "optional analysis extra missing" guards (pyspedas and PyWavelets) are
  verified by forcing the imports to fail.
- The file-in / file-out, serialization, and range logic is exercised against a
  lightweight fake ``pyspedas`` + fake ``pywt`` injected into ``sys.modules``.

A real-backend round-trip is provided as an opt-in test that skips when the
``[analysis]`` extra is not installed.
"""
from __future__ import annotations

import builtins
import importlib
import json
import sys
import types
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from spedas_agent_kit.analysis import spectral


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def channel_csv(tmp_path: Path) -> Path:
    """A small single-channel time-series CSV (Unix-time first column)."""
    n = 512
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame(
        {
            "time": t,
            "bx": np.sin(2 * np.pi * t / 32.0),
            "by": np.cos(2 * np.pi * t / 16.0),
        }
    )
    path = tmp_path / "scalar.csv"
    df.to_csv(path, index=False)
    return path


def _install_fake_pyspedas(monkeypatch, **overrides):
    """Install a minimal fake ``pyspedas`` tree + fake ``pywt`` into sys.modules."""
    pyspedas = types.ModuleType("pyspedas")
    tplot_tools = types.ModuleType("pyspedas.tplot_tools")
    tplot_math = types.ModuleType("pyspedas.tplot_tools.tplot_math")
    analysis = types.ModuleType("pyspedas.analysis")

    dpwrspc_mod = types.ModuleType("pyspedas.tplot_tools.tplot_math.dpwrspc")
    dpwrspc_mod.dpwrspc = overrides.get("dpwrspc", _default_dpwrspc)

    wavelet_mod = types.ModuleType("pyspedas.analysis.wavelet")
    wavelet_mod.idl_wavelet_scales = overrides.get("scales", _default_scales)

    wave_signif_mod = types.ModuleType("pyspedas.analysis.wave_signif")
    wave_signif_mod.wave_signif = overrides.get("wave_signif", _default_wave_signif)

    pywt_mod = types.ModuleType("pywt")
    pywt_mod.cwt = overrides.get("cwt", _default_cwt)

    modules = {
        "pyspedas": pyspedas,
        "pyspedas.tplot_tools": tplot_tools,
        "pyspedas.tplot_tools.tplot_math": tplot_math,
        "pyspedas.tplot_tools.tplot_math.dpwrspc": dpwrspc_mod,
        "pyspedas.analysis": analysis,
        "pyspedas.analysis.wavelet": wavelet_mod,
        "pyspedas.analysis.wave_signif": wave_signif_mod,
        "pywt": pywt_mod,
    }
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return pyspedas


def _default_dpwrspc(time, quantity, nboxpoints=256, nshiftpoints=128, bin=3, nohanning=False):
    n = len(time)
    nwin = max(1, (n - nboxpoints) // nshiftpoints)
    nfreq = max(2, nboxpoints // (2 * bin))
    tdps = np.asarray(time, dtype="float64")[:nwin]
    freq_axis = np.linspace(0.0, 0.5, nfreq)
    fdps = np.tile(freq_axis, (nwin, 1))
    dps = np.ones((nwin, nfreq), dtype="float64")
    return tdps, fdps, dps


def _default_scales(n, dt, w0=None, dj=None):
    # 12 log-spaced scales.  The pyspedas helper follows the
    # Torrence-Compo convention where returned scales/periods are in the same
    # physical units as the supplied cadence.
    scales = np.geomspace(2.0, 64.0, 12) * float(dt)
    periods = scales * 1.03  # fourier_factor ~ 0.97 for Morlet w0=2pi
    freqs = 1.0 / periods
    return scales, freqs, periods


def _default_cwt(data, scales=None, wavelet=None, method="fft", sampling_period=1.0):
    nscale = len(scales)
    ntime = len(data)
    coef = np.ones((nscale, ntime), dtype="float64")
    freqs = 1.0 / (np.asarray(scales, dtype="float64") * float(sampling_period) * 1.03)
    return coef, freqs


def _default_wave_signif(Y, dt, scale, sigtest, siglvl=0.95, mother="MORLET", **kwargs):
    signif = np.full(len(scale), 0.5, dtype="float64")
    return signif, {"period": np.asarray(scale) * 1.03}


# --------------------------------------------------------------------------
# Validation (no backend needed)
# --------------------------------------------------------------------------

def test_dpwrspc_rejects_nonpositive_window(channel_csv, tmp_path):
    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
        nboxpoints=0,
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "nboxpoints" in out["message"]


def test_wavelet_rejects_unknown_wavename(channel_csv, tmp_path):
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        wavename="",
    )
    assert out["status"] == "error"
    assert "supported_wavelets" in out


def test_wavelet_rejects_bad_period_band(channel_csv, tmp_path):
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        min_period=100.0,
        max_period=10.0,
    )
    assert out["status"] == "error"
    assert "min_period" in out["message"]


def test_wavelet_rejects_bad_siglvl(channel_csv, tmp_path):
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        siglvl=1.5,
    )
    assert out["status"] == "error"
    assert "siglvl" in out["message"]


# --------------------------------------------------------------------------
# Missing-extra guards
# --------------------------------------------------------------------------

def test_dpwrspc_missing_pyspedas(channel_csv, tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas" or name.startswith("pyspedas."):
            raise ModuleNotFoundError("No module named 'pyspedas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
    )
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"
    assert "spedas-agent-kit[analysis]" in out["message"]


def test_wavelet_missing_pywt(channel_csv, tmp_path, monkeypatch):
    # pyspedas imports fine, but PyWavelets is absent.
    _install_fake_pyspedas(monkeypatch)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pywt":
            raise ModuleNotFoundError("No module named 'pywt'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pywt", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
    )
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"
    assert "PyWavelets" in out["message"]


# --------------------------------------------------------------------------
# Logic with fake backends
# --------------------------------------------------------------------------

def test_dpwrspc_writes_spectrogram(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
        data_col="bx",
        nboxpoints=128,
        nshiftpoints=64,
    )
    assert out["status"] == "success"
    assert out["data_col"] == "bx"
    assert len(out["shape"]) == 2
    assert out["hanning"] is True
    spec = Path(out["spectrogram_file"])
    assert spec.exists()
    npz = np.load(spec)
    assert npz["power"].ndim == 2
    assert "time" in npz and "freq" in npz
    assert npz["freq"].ndim == 1
    assert npz["freq"].shape[0] == npz["power"].shape[1]
    assert len(out["freq_range"]) == 2
    assert len(out["time_range"]) == 2


def test_dpwrspc_rejects_short_interval(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
        nboxpoints=4096,  # more than the 512 samples available
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert out["samples"] == 512


def test_dpwrspc_handles_degenerate_output(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch, dpwrspc=lambda *a, **k: (np.array(-1.0), np.array(-1.0), np.array(-1.0)))
    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
        nboxpoints=128,
    )
    assert out["status"] == "error"
    assert "no spectrum" in out["message"]


def test_wavelet_writes_spectrogram(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        data_col="bx",
        wavename="morl",
    )
    assert out["status"] == "success"
    assert out["data_col"] == "bx"
    assert out["wavename"] == "morl"
    assert out["significance_computed"] is False
    assert out["siglvl"] is None
    assert out["shape"][0] == 512  # n_time rows
    spec = Path(out["spectrogram_file"])
    assert spec.exists()
    npz = np.load(spec)
    assert npz["power"].shape[0] == 512
    assert "period" in npz and "freq" in npz
    assert "significance" not in npz
    assert len(out["period_range"]) == 2


def test_wavelet_uses_sample_unit_scales_for_high_rate_data(tmp_path, monkeypatch):
    n = 512
    dt = 0.1
    t = 1_600_000_000.0 + np.arange(n, dtype="float64") * dt
    csv = tmp_path / "fast.csv"
    pd.DataFrame({"time": t, "b": np.sin(2 * np.pi * np.arange(n) / 32.0)}).to_csv(
        csv, index=False
    )

    calls = {}

    def cadence_scaled_scales(npts, cadence, w0=None, dj=None):
        calls["scale_cadence"] = cadence
        return _default_scales(npts, cadence, w0=w0, dj=dj)

    def rejecting_cwt(data, scales=None, wavelet=None, method="fft", sampling_period=1.0):
        scales_arr = np.asarray(scales, dtype="float64")
        calls["cwt_scales"] = scales_arr
        calls["sampling_period"] = sampling_period
        if float(np.min(scales_arr)) < 1.0:
            raise ValueError(f"Selected scale of {float(np.min(scales_arr))} too small.")
        return _default_cwt(
            data, scales=scales_arr, wavelet=wavelet, method=method, sampling_period=sampling_period
        )

    _install_fake_pyspedas(monkeypatch, scales=cadence_scaled_scales, cwt=rejecting_cwt)

    out = spectral.wavelet_transform(
        input_file=str(csv),
        output_dir=str(tmp_path / "wav"),
        data_col="b",
        wavename="morl",
    )

    assert out["status"] == "success"
    assert calls["scale_cadence"] == 1.0
    assert calls["sampling_period"] == pytest.approx(dt)
    assert float(np.min(calls["cwt_scales"])) >= 1.0
    npz = np.load(out["spectrogram_file"])
    assert float(np.min(npz["period"])) == pytest.approx(2.0 * 1.03 * dt)
    assert out["period_range"][0] == pytest.approx(2.0 * 1.03 * dt)


def test_wavelet_preserves_pywavelets_frequency_axis_for_other_wavelets(
    tmp_path, monkeypatch
):
    n = 128
    dt = 0.25
    t = 1_600_000_000.0 + np.arange(n, dtype="float64") * dt
    csv = tmp_path / "fast_mexh.csv"
    pd.DataFrame({"time": t, "b": np.sin(2 * np.pi * np.arange(n) / 16.0)}).to_csv(
        csv, index=False
    )
    factor = 2.5

    def custom_axis_cwt(data, scales=None, wavelet=None, method="fft", sampling_period=1.0):
        assert wavelet == "mexh"
        scales_arr = np.asarray(scales, dtype="float64")
        coef = np.ones((scales_arr.size, len(data)), dtype="float64")
        freqs = 1.0 / (scales_arr * float(sampling_period) * factor)
        return coef, freqs

    _install_fake_pyspedas(monkeypatch, cwt=custom_axis_cwt)

    out = spectral.wavelet_transform(
        input_file=str(csv),
        output_dir=str(tmp_path / "wav"),
        data_col="b",
        wavename="mexh",
    )

    assert out["status"] == "success"
    npz = np.load(out["spectrogram_file"])
    sample_scales, _freqs, idl_periods = _default_scales(n, 1.0)
    expected_periods = sample_scales * dt * factor
    assert np.allclose(npz["period"], expected_periods)
    assert not np.allclose(npz["period"], idl_periods * dt)
    assert np.allclose(npz["freq"], 1.0 / expected_periods)


def test_wavelet_regular_cadence_has_no_warning(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        data_col="bx",
    )
    assert out["status"] == "success"
    # channel_csv is a clean 1 s cadence -> dt detected, no irregular-cadence flag
    assert out["sampling_interval_s"] == 1.0
    assert out["cadence_warning"] is None


def test_wavelet_irregular_cadence_warns_and_uses_median_dt(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    # One 1 s gap up front, then all 10 s gaps: a naive first-gap dt (=1 s) would
    # mislabel the axes by 10x for 99% of the series. The tool should instead use
    # the median spacing (10 s) and surface a cadence warning.
    n = 256
    t = [1_600_000_000.0, 1_600_000_001.0]
    for _ in range(n - 2):
        t.append(t[-1] + 10.0)
    df = pd.DataFrame({"time": np.asarray(t), "bx": np.sin(np.arange(n) / 5.0)})
    path = tmp_path / "irregular.csv"
    df.to_csv(path, index=False)

    out = spectral.wavelet_transform(
        input_file=str(path),
        output_dir=str(tmp_path / "wav"),
        data_col="bx",
    )
    assert out["status"] == "success"
    assert out["sampling_interval_s"] == 10.0  # median, not the stray 1 s first gap
    assert out["cadence_warning"] is not None
    assert "irregular cadence" in out["cadence_warning"]


def test_wavelet_with_significance(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        wavename="morl",
        compute_significance=True,
        siglvl=0.99,
    )
    assert out["status"] == "success"
    assert out["significance_computed"] is True
    assert out["siglvl"] == 0.99
    npz = np.load(out["spectrogram_file"])
    assert "significance" in npz


def test_wavelet_period_band_filters_scales(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    full = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "full"),
        wavename="morl",
    )
    banded = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "banded"),
        wavename="morl",
        min_period=10.0,
        max_period=40.0,
    )
    assert full["status"] == "success" and banded["status"] == "success"
    # The banded transform keeps strictly fewer frequencies than the full grid.
    assert banded["shape"][1] < full["shape"][1]


def test_wavelet_empty_period_band(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.wavelet_transform(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "wav"),
        min_period=1e6,
        max_period=1e7,
    )
    assert out["status"] == "error"
    assert "natural_period_range" in out


def test_wavelet_rejects_all_nan_data_column_before_scales(tmp_path, monkeypatch):
    def fail_scales(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("idl_wavelet_scales should not run for all-NaN data")

    _install_fake_pyspedas(monkeypatch, scales=fail_scales)
    n = 300
    csv = tmp_path / "all_nan.csv"
    pd.DataFrame(
        {
            "time": np.arange(n, dtype="float64"),
            "v": np.full(n, np.nan),
        }
    ).to_csv(csv, index=False)

    out = spectral.wavelet_transform(
        input_file=str(csv),
        output_dir=str(tmp_path / "wav"),
        data_col="v",
    )

    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert out["data_col"] == "v"
    assert out["finite_samples"] == 0
    assert out["total_samples"] == n
    assert out["min_finite_samples"] == 2
    assert "finite samples" in out["message"]
    assert "Selected scale" not in out["message"]


def test_wavelet_rejects_near_empty_finite_data_column_before_scales(tmp_path, monkeypatch):
    def fail_scales(*args, **kwargs):  # pragma: no cover - should not be called
        raise AssertionError("idl_wavelet_scales should not run for near-empty data")

    _install_fake_pyspedas(monkeypatch, scales=fail_scales)
    n = 300
    values = np.full(n, np.nan)
    values[17] = 1.0
    csv = tmp_path / "one_finite.csv"
    pd.DataFrame({"time": np.arange(n, dtype="float64"), "v": values}).to_csv(
        csv, index=False
    )

    out = spectral.wavelet_transform(
        input_file=str(csv),
        output_dir=str(tmp_path / "wav"),
        data_col="v",
    )

    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert out["data_col"] == "v"
    assert out["finite_samples"] == 1
    assert out["total_samples"] == n
    assert out["min_finite_samples"] == 2
    assert "finite samples" in out["message"]
    assert "Selected scale" not in out["message"]


# --------------------------------------------------------------------------
# Input-parsing robustness
# --------------------------------------------------------------------------

def test_channel_loader_autodetects_first_numeric(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
        nboxpoints=128,
    )
    assert out["status"] == "success"
    assert out["data_col"] == "bx"  # first numeric non-time column


def test_channel_loader_rejects_missing_col(channel_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.dynamic_power_spectrum(
        input_file=str(channel_csv),
        output_dir=str(tmp_path / "dps"),
        data_col="not_a_col",
        nboxpoints=128,
    )
    assert out["status"] == "error"
    assert "not_a_col" in out["message"]


def test_channel_loader_supports_json(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    n = 300
    t = (np.arange(n, dtype="float64") + 1_600_000_000.0)
    payload = {"time": t.tolist(), "b": np.sin(t / 10.0).tolist()}
    jpath = tmp_path / "vec.json"
    jpath.write_text(json.dumps(payload), encoding="utf-8")
    out = spectral.dynamic_power_spectrum(
        input_file=str(jpath),
        output_dir=str(tmp_path / "dps"),
        data_col="b",
        nboxpoints=128,
        nshiftpoints=64,
    )
    assert out["status"] == "success"
    assert out["data_col"] == "b"


def test_loader_missing_file(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = spectral.dynamic_power_spectrum(
        input_file=str(tmp_path / "nope.csv"),
        output_dir=str(tmp_path / "dps"),
    )
    assert out["status"] == "error"
    assert "does not exist" in out["message"]


# --------------------------------------------------------------------------
# Opt-in real backend round-trip (skips without the [analysis] extra)
# --------------------------------------------------------------------------

def _have_backends() -> bool:
    required = (
        ("pyspedas", None),
        ("pywt", None),
        ("pyspedas.tplot_tools.tplot_math.dpwrspc", "dpwrspc"),
        ("pyspedas.analysis.wavelet", "idl_wavelet_scales"),
        ("pyspedas.analysis.wave_signif", "wave_signif"),
    )
    for module_name, attr_name in required:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            return False
        if attr_name is not None and not hasattr(module, attr_name):
            return False
    return True


@pytest.mark.skipif(not _have_backends(), reason="requires spedas-agent-kit[analysis] (pyspedas + pywt)")
def test_real_dpwrspc_roundtrip(tmp_path):
    n = 2048
    t = np.arange(n, dtype="float64")
    sig = np.sin(2 * np.pi * t / 16.0)
    df = pd.DataFrame({"time": t, "b": sig})
    csv = tmp_path / "wave.csv"
    df.to_csv(csv, index=False)
    out = spectral.dynamic_power_spectrum(
        input_file=str(csv), output_dir=str(tmp_path / "dps"),
        data_col="b", nboxpoints=256, nshiftpoints=128,
    )
    assert out["status"] == "success"
    npz = np.load(out["spectrogram_file"])
    assert npz["power"].ndim == 2


@pytest.mark.skipif(not _have_backends(), reason="requires spedas-agent-kit[analysis] (pyspedas + pywt)")
def test_real_wavelet_roundtrip(tmp_path):
    n = 1024
    t = np.arange(n, dtype="float64")
    sig = np.sin(2 * np.pi * t / 32.0)
    df = pd.DataFrame({"time": t, "b": sig})
    csv = tmp_path / "wave.csv"
    df.to_csv(csv, index=False)
    out = spectral.wavelet_transform(
        input_file=str(csv), output_dir=str(tmp_path / "wav"),
        data_col="b", wavename="morl", compute_significance=True,
    )
    assert out["status"] == "success"
    npz = np.load(out["spectrogram_file"])
    assert npz["power"].shape[0] == n
    assert "significance" in npz
