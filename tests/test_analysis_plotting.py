"""Offline tests for the artifact renderer ``render_tplot`` (issue #20).

Like ``test_analysis_spectral.py``, these run without network access and without
a real ``matplotlib`` install:

- Argument validation happens before the backend import and is checked directly.
- The "optional analysis extra missing" guard (matplotlib) is verified by forcing
  the import to fail.
- The load / auto-detect / trange / log-scaling / serialization logic is
  exercised against a lightweight fake ``matplotlib`` injected into
  ``sys.modules`` that records the draw calls and writes a real (tiny) PNG file.

A real-backend round-trip is provided as an opt-in test that skips when the
``[analysis]`` extra (matplotlib) is not installed.
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

from spedas_agent_kit.analysis import plotting


# --------------------------------------------------------------------------
# Fixtures: synthetic artifacts mirroring the spectral / particle / data tools
# --------------------------------------------------------------------------

@pytest.fixture
def spectrogram_npz(tmp_path: Path) -> Path:
    """A spectral-tool-style spectrogram .npz (power matrix + time/freq axes)."""
    n_time, n_freq = 40, 16
    t = np.arange(n_time, dtype="float64") + 1_600_000_000.0
    freq = np.linspace(0.01, 0.5, n_freq)
    power = np.abs(np.random.default_rng(0).standard_normal((n_time, n_freq))) + 0.1
    path = tmp_path / "spec.npz"
    np.savez_compressed(path, time=t, freq=freq, power=power)
    return path


@pytest.fixture
def particle_spectrogram_npz(tmp_path: Path) -> Path:
    """A particle-spectra-style .npz (spectrogram matrix + time/axis axes)."""
    n_time, n_bin = 30, 12
    t = np.arange(n_time, dtype="float64") + 1_600_000_000.0
    axis = np.linspace(10.0, 1000.0, n_bin)
    spectrogram = np.abs(np.random.default_rng(1).standard_normal((n_time, n_bin))) + 0.1
    path = tmp_path / "pspec.npz"
    np.savez_compressed(path, time=t, axis=axis, spectrogram=spectrogram)
    return path


@pytest.fixture
def labeled_pad_npz(tmp_path: Path) -> Path:
    """A PAD-style spectra .npz that is self-describing (issue #150).

    Mirrors what ``compute_particle_spectra(["pitch_angle"])`` now writes: the
    spectrogram matrix plus optional ``axis_label`` / ``axis_units`` /
    ``value_label`` string keys.
    """
    n_time, n_pa = 24, 18
    t = np.arange(n_time, dtype="float64") + 1_600_000_000.0
    axis = np.linspace(5.0, 175.0, n_pa)
    spectrogram = np.abs(np.random.default_rng(2).standard_normal((n_time, n_pa))) + 0.1
    path = tmp_path / "particle_spectra_pitch_angle.npz"
    np.savez_compressed(
        path,
        time=t,
        axis=axis,
        spectrogram=spectrogram,
        axis_label="pitch_angle",
        axis_units="deg",
        value_label="flux",
    )
    return path


@pytest.fixture
def line_csv(tmp_path: Path) -> Path:
    """A data-layer-style CSV time-series (time + two numeric channels)."""
    n = 50
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame({"time": t, "bx": np.sin(t / 10.0), "by": np.cos(t / 7.0)})
    path = tmp_path / "ts.csv"
    df.to_csv(path, index=False)
    return path


@pytest.fixture
def positive_line_csv(tmp_path: Path) -> Path:
    """A strictly-positive CSV time-series (safe for ylog)."""
    n = 50
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame({"time": t, "flux": np.linspace(1.0, 100.0, n)})
    path = tmp_path / "pos.csv"
    df.to_csv(path, index=False)
    return path


# --------------------------------------------------------------------------
# Fake matplotlib (records calls, writes a real tiny PNG on savefig)
# --------------------------------------------------------------------------

class _FakeXAxis:
    def __init__(self):
        self.locator = None
        self.formatter = None

    def set_major_locator(self, locator):
        self.locator = locator

    def set_major_formatter(self, formatter):
        self.formatter = formatter


class _FakeAxes:
    def __init__(self):
        self.calls: list[str] = []
        self.plot_args: list[tuple[tuple, dict]] = []
        self.pcolormesh_args: list[tuple[tuple, dict]] = []
        self.scatter_args: list[tuple[tuple, dict]] = []
        self.xlabel = None
        self.ylabel = None
        self.xaxis = _FakeXAxis()

    def plot(self, *a, **k):
        self.calls.append("plot")
        self.plot_args.append((a, k))

    def pcolormesh(self, *a, **k):
        self.calls.append("pcolormesh")
        self.pcolormesh_args.append((a, k))
        return object()

    def scatter(self, *a, **k):
        self.calls.append("scatter")
        self.scatter_args.append((a, k))
        return object()

    def set_yscale(self, *a, **k):
        self.calls.append(f"yscale:{a[0] if a else ''}")

    def set_ylabel(self, *a, **k):
        self.ylabel = a[0] if a else None

    def set_xlabel(self, *a, **k):
        self.xlabel = a[0] if a else None

    def legend(self, *a, **k):
        self.calls.append("legend")


class _FakeFigure:
    def __init__(self, n):
        self._axes = [_FakeAxes() for _ in range(n)]
        self.colorbars = 0
        self.colorbar_labels: list[str | None] = []

    def colorbar(self, *a, **k):
        self.colorbars += 1
        self.colorbar_labels.append(k.get("label"))

    def tight_layout(self, *a, **k):
        pass

    def savefig(self, path, *a, **k):
        # Write a minimal but valid 1x1 PNG so callers can stat() a real file.
        Path(path).write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
                "890000000a49444154789c6300010000050001a5f645400000000049454e44ae"
                "426082"
            )
        )


def _install_fake_matplotlib(monkeypatch):
    """Install a minimal fake matplotlib tree into sys.modules; return state."""
    state: dict[str, object] = {"backend": None, "figures": []}

    mpl = types.ModuleType("matplotlib")

    def _use(backend, force=False):
        state["backend"] = backend

    mpl.use = _use

    pyplot = types.ModuleType("matplotlib.pyplot")

    def _subplots(n, m, figsize=None, squeeze=False, sharex=False):
        fig = _FakeFigure(n)
        state["figures"].append(fig)
        # Return axes shaped (n, 1) like squeeze=False.
        axes = np.empty((n, 1), dtype=object)
        for i in range(n):
            axes[i, 0] = fig._axes[i]
        return fig, axes

    pyplot.subplots = _subplots
    pyplot.close = lambda fig: state.__setitem__("closed", True)

    colors = types.ModuleType("matplotlib.colors")

    class _LogNorm:
        def __init__(self, vmin=None, vmax=None):
            self.vmin, self.vmax = vmin, vmax

    colors.LogNorm = _LogNorm

    dates = types.ModuleType("matplotlib.dates")

    class _AutoDateLocator:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _DateFormatter:
        def __init__(self, fmt, *args, **kwargs):
            self.fmt = fmt
            self.args = args
            self.kwargs = kwargs

    def _date2num(values):
        from datetime import datetime, timezone
        import numpy as _np

        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        return _np.asarray([(value - epoch).total_seconds() / 86400.0 for value in values])

    dates.AutoDateLocator = _AutoDateLocator
    dates.DateFormatter = _DateFormatter
    dates.date2num = _date2num

    monkeypatch.setitem(sys.modules, "matplotlib", mpl)
    monkeypatch.setitem(sys.modules, "matplotlib.pyplot", pyplot)
    monkeypatch.setitem(sys.modules, "matplotlib.colors", colors)
    monkeypatch.setitem(sys.modules, "matplotlib.dates", dates)
    return state


# --------------------------------------------------------------------------
# Validation (no backend needed)
# --------------------------------------------------------------------------

def test_rejects_empty_input_files(tmp_path):
    out = plotting.render_tplot(input_files=[], output_file=str(tmp_path / "o.png"))
    assert out["status"] == "error"
    assert "input_files" in out["message"]


def test_rejects_non_png_output(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.pdf")
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert ".png" in out["message"]


def test_rejects_bad_dpi(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.png"), dpi=5000
    )
    assert out["status"] == "error"
    assert "dpi" in out["message"]


def test_rejects_bad_xsize(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.png"), xsize=0
    )
    assert out["status"] == "error"
    assert "xsize" in out["message"]


def test_rejects_panel_types_length_mismatch(tmp_path, spectrogram_npz, line_csv):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz), str(line_csv)],
        output_file=str(tmp_path / "o.png"),
        panel_types=["spectrogram"],  # only one for two inputs
    )
    assert out["status"] == "error"
    assert "panel_types" in out["message"]


def test_rejects_unknown_panel_type(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        panel_types=["heatmap"],
    )
    assert out["status"] == "error"
    assert "supported_panel_types" in out


def test_rejects_bad_trange_length(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        trange=["2020-01-01"],
    )
    assert out["status"] == "error"
    assert "trange" in out["message"]


def test_rejects_unparseable_trange(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        trange=["not-a-time", "also-bad"],
    )
    assert out["status"] == "error"
    assert "trange" in out["message"]


def test_rejects_inverted_trange(tmp_path, spectrogram_npz):
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        trange=[1_600_000_100.0, 1_600_000_000.0],
    )
    assert out["status"] == "error"
    assert "start" in out["message"]


def test_rejects_missing_input_file(tmp_path):
    out = plotting.render_tplot(
        input_files=[str(tmp_path / "nope.npz")], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "error"
    assert out["code"] == "resource_not_found"


# --------------------------------------------------------------------------
# Missing-extra guard
# --------------------------------------------------------------------------

def test_missing_matplotlib(tmp_path, spectrogram_npz, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ModuleNotFoundError("No module named 'matplotlib'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "matplotlib", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"
    assert "spedas-agent-kit[analysis]" in out["message"]


# --------------------------------------------------------------------------
# Logic with fake matplotlib
# --------------------------------------------------------------------------

def test_renders_spectrogram_panel(tmp_path, spectrogram_npz, monkeypatch):
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    assert out["n_panels"] == 1
    assert Path(out["output_file"]).exists()
    assert out["panels"][0]["type"] == "spectrogram"
    assert out["panels"][0]["shape"] == [40, 16]
    assert out["panels"][0]["axis_range"] is not None
    assert out["size_px"] == [int(12 * 200), out["size_px"][1]]
    # The Agg backend must be forced and a colorbar drawn for the spectrogram.
    assert state["backend"] == "Agg"
    assert state["figures"][0].colorbars == 1


def test_spectrogram_prefers_embedded_axis_labels(tmp_path, labeled_pad_npz, monkeypatch):
    # Issue #150: a self-describing PAD .npz drives the y-axis label ("pitch_angle
    # [deg]") and colorbar label ("flux") instead of the filename stem.
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(labeled_pad_npz)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "spectrogram"
    # Returned metadata surfaces the resolved label, and it is NOT the stem.
    assert panel["axis_label"] == "pitch_angle [deg]"
    assert panel["axis_label"] != Path(labeled_pad_npz).stem
    assert panel["value_label"] == "flux"
    # The y-axis and colorbar are labeled from the embedded keys.
    fig = state["figures"][0]
    assert fig._axes[0].ylabel == "pitch_angle [deg]"
    assert fig.colorbar_labels == ["flux"]


def test_spectrogram_falls_back_to_stem_for_unlabeled_npz(
    tmp_path, particle_spectrogram_npz, monkeypatch
):
    # Back-compat: an older artifact without the issue #150 label keys still
    # renders, with the filename stem as the y-axis label and no colorbar label.
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(particle_spectrogram_npz)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "spectrogram"
    stem = Path(particle_spectrogram_npz).stem
    assert panel["axis_label"] == stem
    assert "value_label" not in panel
    fig = state["figures"][0]
    assert fig._axes[0].ylabel == stem
    assert fig.colorbar_labels == [None]


# --------------------------------------------------------------------------
# Issue #154: line/scatter panels propagate embedded/sidecar labels
# --------------------------------------------------------------------------

@pytest.fixture
def labeled_line_npz(tmp_path: Path) -> Path:
    """A self-describing single-series line .npz (issue #154).

    Mirrors what a field-model writer could emit: a 1-D value array plus the
    optional ``axis_label`` / ``axis_units`` / ``value_label`` string keys.
    """
    n = 30
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    bmag = np.linspace(5.0, 40.0, n)
    path = tmp_path / "b_magnitude.npz"
    np.savez_compressed(
        path,
        time=t,
        bmag=bmag,
        axis_label="B magnitude",
        axis_units="nT",
        value_label="B",
    )
    return path


def test_line_npz_prefers_embedded_axis_labels(tmp_path, labeled_line_npz, monkeypatch):
    # A labeled line .npz drives the y-axis label ("B magnitude [nT]") and
    # surfaces the label/value metadata instead of the filename stem.
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(labeled_line_npz)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "line"
    assert panel["axis_label"] == "B magnitude [nT]"
    assert panel["axis_label"] != Path(labeled_line_npz).stem
    assert panel["value_label"] == "B"
    fig = state["figures"][0]
    assert fig._axes[0].ylabel == "B magnitude [nT]"


def test_line_npz_falls_back_to_stem_when_unlabeled(tmp_path, monkeypatch):
    # Back-compat: a label-less line .npz keeps the filename-stem y-axis label.
    state = _install_fake_matplotlib(monkeypatch)
    t = np.arange(20, dtype="float64") + 1_600_000_000.0
    lshell = np.linspace(2.0, 6.0, 20)
    p = tmp_path / "lshell.npz"
    np.savez_compressed(p, time=t, lshell=lshell)
    out = plotting.render_tplot(input_files=[str(p)], output_file=str(tmp_path / "o.png"))
    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "line"
    stem = Path(p).stem
    assert panel["axis_label"] == stem
    assert "value_label" not in panel
    assert state["figures"][0]._axes[0].ylabel == stem


def test_line_csv_consumes_labels_sidecar(tmp_path, monkeypatch):
    # A CSV table with a sibling <name>.labels.json sidecar labels the y-axis.
    state = _install_fake_matplotlib(monkeypatch)
    n = 25
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame({"time": t, "density": np.linspace(1.0, 9.0, n)})
    csv_path = tmp_path / "density.csv"
    df.to_csv(csv_path, index=False)
    sidecar = tmp_path / "density.csv.labels.json"
    sidecar.write_text(
        json.dumps(
            {"axis_label": "ion density", "axis_units": "cm^-3", "value_label": "n"}
        ),
        encoding="utf-8",
    )
    out = plotting.render_tplot(
        input_files=[str(csv_path)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "line"
    assert panel["axis_label"] == "ion density [cm^-3]"
    assert panel["value_label"] == "n"
    assert state["figures"][0]._axes[0].ylabel == "ion density [cm^-3]"


def test_line_csv_without_sidecar_keeps_stem(tmp_path, line_csv, monkeypatch):
    # No sidecar -> filename-stem fallback, unchanged legacy behavior.
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(line_csv)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    panel = out["panels"][0]
    stem = Path(line_csv).stem
    assert panel["axis_label"] == stem
    assert "value_label" not in panel
    assert state["figures"][0]._axes[0].ylabel == stem


def test_line_csv_ignores_malformed_sidecar(tmp_path, line_csv, monkeypatch):
    # A corrupt / non-object sidecar is ignored rather than failing the render.
    state = _install_fake_matplotlib(monkeypatch)
    (Path(str(line_csv) + ".labels.json")).write_text("not json{", encoding="utf-8")
    out = plotting.render_tplot(
        input_files=[str(line_csv)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    assert out["panels"][0]["axis_label"] == Path(line_csv).stem


def test_scatter_npz_surfaces_embedded_labels(tmp_path, monkeypatch):
    # An explicit scatter panel surfaces embedded matrix labels as metadata
    # without overriding the per-column x/y tick labels.
    state = _install_fake_matplotlib(monkeypatch)
    t = np.arange(15, dtype="float64") + 1_600_000_000.0
    b_gsm = np.column_stack([np.arange(15), np.arange(15) + 5, np.arange(15) + 9])
    p = tmp_path / "b.npz"
    np.savez_compressed(
        p, time=t, b_gsm=b_gsm, axis_label="B field", axis_units="nT", value_label="B"
    )
    out = plotting.render_tplot(
        input_files=[str(p)], output_file=str(tmp_path / "xy.png"), panel_types="xy"
    )
    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "scatter"
    assert panel["axis_label"] == "B field [nT]"
    assert panel["value_label"] == "B"
    ax = state["figures"][0]._axes[0]
    # Per-column axis labels still drive the x/y tick labels.
    assert ax.xlabel == "b_gsm[0]"
    assert ax.ylabel == "b_gsm[1]"


def test_renders_line_panel_with_two_series(tmp_path, line_csv, monkeypatch):
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(line_csv)], output_file=str(tmp_path / "o.png")
    )
    assert out["status"] == "success"
    assert out["panels"][0]["type"] == "line"
    assert out["panels"][0]["n_series"] == 2
    fig = state["figures"][0]
    assert fig._axes[0].calls.count("plot") == 2
    assert "legend" in fig._axes[0].calls


def test_multi_panel_mixed(tmp_path, spectrogram_npz, line_csv, particle_spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz), str(line_csv), str(particle_spectrogram_npz)],
        output_file=str(tmp_path / "multi.png"),
    )
    assert out["status"] == "success"
    assert out["n_panels"] == 3
    types_seen = [p["type"] for p in out["panels"]]
    assert types_seen == ["spectrogram", "line", "spectrogram"]


def test_panel_type_override_forces_line_on_npz(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        panel_types="line",  # scalar broadcast; force a line interpretation
    )
    assert out["status"] == "success"
    assert out["panels"][0]["type"] == "line"



def test_renders_scatter_npz_default_components(tmp_path, monkeypatch):
    state = _install_fake_matplotlib(monkeypatch)
    t = np.arange(25, dtype="float64") + 1_600_000_000.0
    values = np.column_stack([np.sin(np.arange(25) / 3.0), np.cos(np.arange(25) / 3.0), np.arange(25)])
    p = tmp_path / "bvec.npz"
    np.savez_compressed(p, time=t, values=values)

    out = plotting.render_tplot(
        input_files=[str(p)], output_file=str(tmp_path / "xy.png"), panel_types="xy"
    )

    assert out["status"] == "success"
    panel = out["panels"][0]
    assert panel["type"] == "scatter"
    assert panel["shape"] == [25, 3]
    assert panel["components"] == [0, 1]
    assert panel["matrix_key"] == "values"
    assert panel["x_range"] is not None and panel["y_range"] is not None
    ax = state["figures"][0]._axes[0]
    assert "plot" in ax.calls
    assert "scatter" in ax.calls
    assert ax.xlabel == "values[0]"
    assert ax.ylabel == "values[1]"


def test_scatter_npz_selects_components(tmp_path, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    t = np.arange(10, dtype="float64") + 1_600_000_000.0
    b_gsm = np.column_stack([np.arange(10), np.arange(10) + 10, np.arange(10) + 20])
    p = tmp_path / "b.npz"
    np.savez_compressed(p, time=t, b_gsm=b_gsm)

    out = plotting.render_tplot(
        input_files=[str(p)],
        output_file=str(tmp_path / "xz.png"),
        panel_types=["hodogram"],
        x_component=[0],
        y_component=[2],
    )

    assert out["status"] == "success"
    assert out["panels"][0]["components"] == [0, 2]
    assert out["panels"][0]["matrix_key"] == "b_gsm"
    assert out["panels"][0]["y_range"] == [20.0, 29.0]


def test_scatter_component_out_of_bounds_errors(tmp_path, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    p = tmp_path / "two_col.npz"
    np.savez_compressed(p, values=np.ones((5, 2)))

    out = plotting.render_tplot(
        input_files=[str(p)],
        output_file=str(tmp_path / "bad.png"),
        panel_types="scatter",
        y_component=3,
    )

    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "out of bounds" in out["message"]


def test_scatter_table_uses_numeric_columns(tmp_path, line_csv, monkeypatch):
    state = _install_fake_matplotlib(monkeypatch)

    out = plotting.render_tplot(
        input_files=[str(line_csv)],
        output_file=str(tmp_path / "csv_xy.png"),
        panel_types="scatter",
        x_component=1,
        y_component=0,
    )

    assert out["status"] == "success"
    assert out["panels"][0]["type"] == "scatter"
    assert out["panels"][0]["components"] == [1, 0]
    ax = state["figures"][0]._axes[0]
    assert ax.xlabel == "by"
    assert ax.ylabel == "bx"

def test_zlog_applied_to_spectrogram(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        zlog=True,
    )
    assert out["status"] == "success"
    assert out["panels"][0]["zlog"] is True


def test_ylog_rejected_on_nonpositive(tmp_path, line_csv, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(line_csv)],  # bx/by include negatives
        output_file=str(tmp_path / "o.png"),
        ylog=True,
    )
    assert out["status"] == "error"
    assert "ylog" in out["message"]
    assert out["code"] == "invalid_argument"


def test_ylog_ok_on_positive(tmp_path, positive_line_csv, monkeypatch):
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(positive_line_csv)],
        output_file=str(tmp_path / "o.png"),
        ylog=[True],
    )
    assert out["status"] == "success"
    assert out["panels"][0]["ylog"] is True
    assert any(c.startswith("yscale:log") for c in state["figures"][0]._axes[0].calls)


def test_trange_filters_samples(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    # Keep only the first 10 of 40 time steps (Unix base + [0,9]).
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        trange=[1_600_000_000.0, 1_600_000_009.0],
    )
    assert out["status"] == "success"
    assert out["panels"][0]["shape"][0] == 10
    assert out["trange"]["requested"] == [1_600_000_000.0, 1_600_000_009.0]


def test_trange_excluding_everything_errors(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        trange=[1_700_000_000.0, 1_700_000_100.0],
    )
    assert out["status"] == "error"
    assert "trange" in out["message"]


def test_iso_trange_accepted(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    # 1_600_000_000 -> 2020-09-13T12:26:40Z; choose an ISO window covering it.
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)],
        output_file=str(tmp_path / "o.png"),
        trange=["2020-09-13T12:26:40Z", "2020-09-13T12:27:00Z"],
    )
    assert out["status"] == "success"
    assert out["trange"]["requested"][0] == pytest.approx(1_600_000_000.0)


def test_creates_parent_dirs(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    nested = tmp_path / "a" / "b" / "out.png"
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(nested)
    )
    assert out["status"] == "success"
    assert nested.exists()


def test_no_image_bytes_in_payload(tmp_path, spectrogram_npz, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.png")
    )
    blob = json.dumps(out)
    # The serialized payload must stay tiny: no inlined arrays/image bytes.
    assert len(blob) < 4000
    assert "data:image" not in blob


def test_npz_value_array_as_line(tmp_path, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    # A bare value series .npz (e.g. an L-shell series) with a time axis.
    t = np.arange(20, dtype="float64") + 1_600_000_000.0
    lshell = np.linspace(2.0, 6.0, 20)
    p = tmp_path / "lshell.npz"
    np.savez_compressed(p, time=t, lshell=lshell)
    out = plotting.render_tplot(input_files=[str(p)], output_file=str(tmp_path / "o.png"))
    assert out["status"] == "success"
    assert out["panels"][0]["type"] == "line"


def test_json_timeseries_as_line(tmp_path, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    t = (np.arange(15, dtype="float64") + 1_600_000_000.0).tolist()
    payload = {"time": t, "b": np.sin(np.arange(15) / 3.0).tolist()}
    p = tmp_path / "ts.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    out = plotting.render_tplot(input_files=[str(p)], output_file=str(tmp_path / "o.png"))
    assert out["status"] == "success"
    assert out["panels"][0]["type"] == "line"


def test_spectrogram_request_on_table_errors(tmp_path, line_csv, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(line_csv)],
        output_file=str(tmp_path / "o.png"),
        panel_types=["spectrogram"],
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"


def test_unsupported_extension_errors(tmp_path, monkeypatch):
    _install_fake_matplotlib(monkeypatch)
    bad = tmp_path / "data.txt"
    bad.write_text("nope", encoding="utf-8")
    out = plotting.render_tplot(input_files=[str(bad)], output_file=str(tmp_path / "o.png"))
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"


# --------------------------------------------------------------------------


def test_render_uses_utc_date_axis_for_line_panels(tmp_path, line_csv, monkeypatch):
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(input_files=[str(line_csv)], output_file=str(tmp_path / "o.png"))

    assert out["status"] == "success"
    ax = state["figures"][0]._axes[0]
    assert ax.xlabel == "time (UT)"
    assert ax.xaxis.locator.__class__.__name__ == "_AutoDateLocator"
    assert ax.xaxis.formatter.fmt == "%H:%M\n%m-%d"
    plotted_x = ax.plot_args[0][0][0]
    assert np.nanmax(plotted_x) < 100_000  # Matplotlib date-days, not Unix seconds.
    assert np.nanmin(plotted_x) != out["panels"][0]["time_range"][0]


def test_render_uses_utc_date_axis_for_spectrogram_panels(
    tmp_path, spectrogram_npz, monkeypatch
):
    state = _install_fake_matplotlib(monkeypatch)
    out = plotting.render_tplot(
        input_files=[str(spectrogram_npz)], output_file=str(tmp_path / "o.png")
    )

    assert out["status"] == "success"
    ax = state["figures"][0]._axes[0]
    assert ax.xlabel == "time (UT)"
    plotted_x = ax.pcolormesh_args[0][0][0]
    assert np.nanmax(plotted_x) < 100_000  # Matplotlib date-days, not Unix seconds.

# Opt-in real backend round-trip (skips without matplotlib)
# --------------------------------------------------------------------------

def _have_matplotlib() -> bool:
    try:
        importlib.import_module("matplotlib")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_matplotlib(), reason="requires spedas-agent-kit[analysis] (matplotlib)")
def test_real_render_roundtrip(tmp_path):
    # spectrogram + line, rendered by the real matplotlib Agg backend.
    n_time, n_freq = 32, 12
    t = np.arange(n_time, dtype="float64") + 1_600_000_000.0
    freq = np.linspace(0.01, 0.5, n_freq)
    power = np.abs(np.random.default_rng(2).standard_normal((n_time, n_freq))) + 0.1
    spec = tmp_path / "spec.npz"
    np.savez_compressed(spec, time=t, freq=freq, power=power)

    df = pd.DataFrame({"time": t, "bx": np.sin(t / 5.0)})
    csv = tmp_path / "ts.csv"
    df.to_csv(csv, index=False)

    out = plotting.render_tplot(
        input_files=[str(spec), str(csv)],
        output_file=str(tmp_path / "real.png"),
        zlog=[True, False],
    )
    assert out["status"] == "success"
    png = Path(out["output_file"])
    assert png.exists() and png.stat().st_size > 0
    assert out["n_panels"] == 2


@pytest.mark.skipif(not _have_matplotlib(), reason="requires spedas-agent-kit[analysis] (matplotlib)")
def test_real_render_roundtrip_line_labels(tmp_path):
    # Issue #154: labeled line .npz + sidecar-labeled CSV render with the real
    # backend and surface their resolved labels in the returned metadata.
    n = 30
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    bmag = np.linspace(5.0, 40.0, n)
    npz = tmp_path / "b_magnitude.npz"
    np.savez_compressed(
        npz, time=t, bmag=bmag, axis_label="B magnitude", axis_units="nT", value_label="B"
    )

    df = pd.DataFrame({"time": t, "density": np.linspace(1.0, 9.0, n)})
    csv = tmp_path / "density.csv"
    df.to_csv(csv, index=False)
    (tmp_path / "density.csv.labels.json").write_text(
        json.dumps({"axis_label": "ion density", "axis_units": "cm^-3"}),
        encoding="utf-8",
    )

    out = plotting.render_tplot(
        input_files=[str(npz), str(csv)], output_file=str(tmp_path / "real_labels.png")
    )
    assert out["status"] == "success"
    assert Path(out["output_file"]).stat().st_size > 0
    assert out["panels"][0]["axis_label"] == "B magnitude [nT]"
    assert out["panels"][1]["axis_label"] == "ion density [cm^-3]"
