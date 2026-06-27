"""Offline tests for the Phase-1 coordinate-transform analysis tools.

These tests run without network access and without a real ``pyspedas`` install:

- Frame/argument validation happens before the backend import and is checked
  directly.
- The "optional analysis extra missing" guard is verified by forcing the import
  to fail.
- The file-in/file-out, serialization, and summary logic is exercised against a
  lightweight fake ``pyspedas`` injected into ``sys.modules``.

A real ``pyspedas`` round-trip is provided as an opt-in test that skips when the
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

from spedas_mcp.analysis import coords


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def vector_csv(tmp_path: Path) -> Path:
    """A small Nx3 vector time-series CSV (Unix-time first column)."""
    n = 64
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame(
        {
            "time": t,
            "bx": np.sin(t / 5.0),
            "by": np.cos(t / 5.0),
            "bz": np.linspace(-1.0, 1.0, n),
        }
    )
    path = tmp_path / "mag.csv"
    df.to_csv(path, index=False)
    return path


def _install_fake_pyspedas(monkeypatch, **overrides):
    """Install a minimal fake ``pyspedas`` package tree into sys.modules.

    Returns the root fake module. Individual submodule callables can be supplied
    via overrides keyed by a logical name (cotrans/fac/minvar/...).
    """
    store: dict[str, dict] = {}

    pyspedas = types.ModuleType("pyspedas")
    cotrans_tools = types.ModuleType("pyspedas.cotrans_tools")
    tplot_tools = types.ModuleType("pyspedas.tplot_tools")

    # tplot store/get/del/set_coords backed by a dict.
    def store_data(name, data=None):
        # Faithfully mimic the real pyspedas store_data, which scrubs non-finite
        # timestamps *in place* (``times[cond] = 0``). A read-only array (e.g. a
        # single-column ``df[...].to_numpy()`` view) raises here, reproducing
        # issue #58 in the offline suite rather than only against a live backend.
        x = np.asarray(data["x"])
        if np.issubdtype(x.dtype, np.floating):
            x[np.logical_not(np.isfinite(x))] = 0
        store[name] = {"x": x, "y": np.asarray(data["y"]), "coords": None}
        return True

    def get_data(name):
        if name not in store:
            return None
        entry = store[name]
        return types.SimpleNamespace(times=entry["x"], y=entry["y"])

    def del_data(name):
        store.pop(name, None)

    def set_coords(name, coord):
        if name in store:
            store[name]["coords"] = coord

    def get_coords(name):
        return store.get(name, {}).get("coords")

    tplot_tools.store_data = store_data
    tplot_tools.get_data = get_data
    tplot_tools.del_data = del_data
    tplot_tools.set_coords = set_coords
    tplot_tools.get_coords = get_coords

    # cotrans submodule
    cotrans_mod = types.ModuleType("pyspedas.cotrans_tools.cotrans")
    cotrans_mod.cotrans = overrides.get("cotrans", _default_cotrans)

    # fac_matrix_make submodule
    fac_mod = types.ModuleType("pyspedas.cotrans_tools.fac_matrix_make")
    fac_mod.fac_matrix_make = overrides.get("fac", _make_default_fac(store))

    # minvar submodule
    minvar_mod = types.ModuleType("pyspedas.cotrans_tools.minvar")
    minvar_mod.minvar = overrides.get("minvar", _default_minvar)

    # minvar_matrix_make submodule
    mvm_mod = types.ModuleType("pyspedas.cotrans_tools.minvar_matrix_make")
    mvm_mod.minvar_matrix_make = overrides.get("mvm", _make_default_mvm(store))

    modules = {
        "pyspedas": pyspedas,
        "pyspedas.cotrans_tools": cotrans_tools,
        "pyspedas.tplot_tools": tplot_tools,
        "pyspedas.cotrans_tools.cotrans": cotrans_mod,
        "pyspedas.cotrans_tools.fac_matrix_make": fac_mod,
        "pyspedas.cotrans_tools.minvar": minvar_mod,
        "pyspedas.cotrans_tools.minvar_matrix_make": mvm_mod,
    }
    for name, mod in modules.items():
        monkeypatch.setitem(sys.modules, name, mod)
    return pyspedas, store


def _default_cotrans(time_in=None, data_in=None, coord_in=None, coord_out=None):
    # Identity-ish transform that is clearly distinguishable (negate) so output
    # differs from input; returns ndarray on success.
    return -np.asarray(data_in, dtype="float64")


def _make_default_fac(store):
    def fac_matrix_make(mag_var, other_dim="xgse", pos_var_name=None, newname=None):
        mag = store[mag_var]["y"]
        n = mag.shape[0]
        mats = np.broadcast_to(np.eye(3), (n, 3, 3)).copy()
        store[newname] = {"x": store[mag_var]["x"], "y": mats, "coords": "FAC"}
        return newname

    return fac_matrix_make


def _default_minvar(data):
    data = np.asarray(data, dtype="float64")
    vrot = data.copy()
    eigvecs = np.eye(3)
    eigvals = np.array([3.0, 2.0, 1.0])
    return vrot, eigvecs, eigvals


def _make_default_mvm(store):
    def minvar_matrix_make(in_var, twindow=None, tslide=None, newname=None, evname=None,
                           tminname=None, tmidname=None, tmaxname=None):
        t = store[in_var]["x"]
        nwin = 3
        store[newname] = {"x": t[:nwin], "y": np.broadcast_to(np.eye(3), (nwin, 3, 3)).copy(), "coords": None}
        store[evname] = {"x": t[:nwin], "y": np.ones((nwin, 3)), "coords": None}
        return newname

    return minvar_matrix_make


# --------------------------------------------------------------------------
# Validation (no backend needed)
# --------------------------------------------------------------------------

def test_transform_rejects_unknown_frames(vector_csv, tmp_path):
    out = coords.transform_timeseries_coordinates(
        input_file=str(vector_csv),
        coord_in="bogus",
        coord_out="gsm",
        output_file=str(tmp_path / "out.csv"),
    )
    assert out["status"] == "error"
    # Uniform error envelope (issue #27): code/message replace the legacy
    # ``error`` key.
    assert out["code"] == "invalid_argument"
    assert "coord_in" in out["message"]
    assert "error" not in out
    assert "gse" in out["supported_frames"]


def test_fac_rejects_unknown_mode(vector_csv, tmp_path):
    out = coords.generate_fac_matrix(
        mag_file=str(vector_csv),
        output_file=str(tmp_path / "fac.npy"),
        other_dim="not_a_mode",
    )
    assert out["status"] == "error"
    assert "supported_modes" in out


def test_fac_position_mode_requires_pos_file(vector_csv, tmp_path):
    out = coords.generate_fac_matrix(
        mag_file=str(vector_csv),
        output_file=str(tmp_path / "fac.npy"),
        other_dim="rgeo",  # position-dependent
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "pos_file" in out["message"]
    assert "rgeo" in out["modes_requiring_pos"]


# --------------------------------------------------------------------------
# Missing-extra guard
# --------------------------------------------------------------------------

def test_missing_analysis_extra_returns_clean_error(vector_csv, tmp_path, monkeypatch):
    # Force `import pyspedas` to raise, simulating the [analysis] extra missing.
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas" or name.startswith("pyspedas."):
            raise ModuleNotFoundError("No module named 'pyspedas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = coords.transform_timeseries_coordinates(
        input_file=str(vector_csv),
        coord_in="gse",
        coord_out="gsm",
        output_file=str(tmp_path / "out.csv"),
    )
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"
    assert "spedas-mcp[analysis]" in out["message"]


# --------------------------------------------------------------------------
# Logic with a fake pyspedas backend
# --------------------------------------------------------------------------

def test_transform_writes_output_and_summary(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "transformed.csv"
    out = coords.transform_timeseries_coordinates(
        input_file=str(vector_csv),
        coord_in="gse",
        coord_out="gsm",
        output_file=str(out_file),
        vector_cols=["bx", "by", "bz"],
    )
    assert out["status"] == "success"
    assert out["coord_in"] == "gse" and out["coord_out"] == "gsm"
    assert out["rows"] == 64
    assert out_file.exists()
    df = pd.read_csv(out_file)
    assert list(df.columns) == ["time", "gsm_x", "gsm_y", "gsm_z"]
    assert len(df) == 64
    # summary has 3 components each
    assert len(out["summary"]["mean"]) == 3


def test_load_time_and_vectors_accepts_datetime_string_dtype(tmp_path, monkeypatch):
    """Data-layer CSV artifacts may expose datetime strings with pandas StringDtype."""
    input_path = tmp_path / "datetime_strings.csv"
    input_path.write_text("placeholder", encoding="utf-8")

    frame = pd.DataFrame(
        {
            "time": pd.Series(
                ["2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z"],
                dtype="string",
            ),
            "bx": [1.0, 2.0],
            "by": [3.0, 4.0],
            "bz": [5.0, 6.0],
        }
    )

    monkeypatch.setattr(pd, "read_csv", lambda *args, **kwargs: frame.copy())

    unix_time, vectors, resolved = coords._load_time_and_vectors(str(input_path))

    assert resolved == ["bx", "by", "bz"]
    assert np.all(np.isfinite(unix_time))
    assert unix_time[1] > unix_time[0]
    assert vectors.tolist() == [[1.0, 3.0, 5.0], [2.0, 4.0, 6.0]]


def test_transform_handles_cotrans_failure(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch, cotrans=lambda **kw: 0)
    out = coords.transform_timeseries_coordinates(
        input_file=str(vector_csv),
        coord_in="gse",
        coord_out="gsm",
        output_file=str(tmp_path / "out.csv"),
    )
    assert out["status"] == "error"
    assert "cotrans failed" in out["message"]


def test_fac_matrix_shape_and_file(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "fac.npy"
    out = coords.generate_fac_matrix(
        mag_file=str(vector_csv),
        output_file=str(out_file),
        other_dim="xgse",
        vector_cols=["bx", "by", "bz"],
    )
    assert out["status"] == "success"
    assert out["mode"] == "xgse"
    assert out["matrix_shape"] == [64, 3, 3]
    assert out["used_position"] is False
    assert out_file.exists()
    arr = np.load(out_file)
    assert arr.shape == (64, 3, 3)


def test_load_time_and_vectors_returns_writeable_arrays(vector_csv):
    """Regression for issue #58: a single-column ``df[time].to_numpy()`` view is
    read-only, and pyspedas ``store_data`` writes into the time array in place.
    The loader must hand back writeable, owned copies so the backend's in-place
    non-finite scrub does not raise ``assignment destination is read-only``.
    """
    unix_time, vectors, _ = coords._load_time_and_vectors(
        str(vector_csv), vector_cols=["bx", "by", "bz"]
    )
    assert unix_time.flags.writeable
    assert vectors.flags.writeable
    # The exact in-place write the real store_data performs must not raise.
    unix_time[np.logical_not(np.isfinite(unix_time))] = 0


def test_fac_matrix_csv_input_survives_inplace_time_scrub(vector_csv, tmp_path, monkeypatch):
    """Regression for issue #58 against the (now faithful) fake store_data, which
    scrubs non-finite timestamps in place. Without the loader copy this raised
    ``assignment destination is read-only`` for CSV-derived time arrays.
    """
    _install_fake_pyspedas(monkeypatch)
    out = coords.generate_fac_matrix(
        mag_file=str(vector_csv),
        output_file=str(tmp_path / "fac.npy"),
        other_dim="xgse",
        vector_cols=["bx", "by", "bz"],
    )
    assert out["status"] == "success", out


def test_fac_matrix_with_position_file(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "fac.npz"
    out = coords.generate_fac_matrix(
        mag_file=str(vector_csv),
        output_file=str(out_file),
        other_dim="rgeo",
        pos_file=str(vector_csv),
        vector_cols=["bx", "by", "bz"],
    )
    assert out["status"] == "success"
    assert out["used_position"] is True
    data = np.load(out_file)
    assert data["fac_matrix"].shape == (64, 3, 3)


def test_minvar_full_interval(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = coords.analyze_minvar_coordinates(
        input_file=str(vector_csv),
        output_dir=str(tmp_path / "mva"),
        vector_cols=["bx", "by", "bz"],
    )
    assert out["status"] == "success"
    assert out["mode"] == "full_interval"
    assert out["eigenvalues"] == [3.0, 2.0, 1.0]
    assert out["normal_vector"] == [0.0, 0.0, 1.0]  # 3rd col of identity
    assert out["intermediate_to_min_ratio"] == 2.0
    assert Path(out["rotated_file"]).exists()
    rot = pd.read_csv(out["rotated_file"])
    assert list(rot.columns) == ["time", "L", "M", "N"]


def test_minvar_sliding_window(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = coords.analyze_minvar_coordinates(
        input_file=str(vector_csv),
        output_dir=str(tmp_path / "mva"),
        twindow=10.0,
        tslide=5.0,
        vector_cols=["bx", "by", "bz"],
    )
    assert out["status"] == "success"
    assert out["mode"] == "sliding_window"
    assert out["windows"] == 3
    assert out["matrix_shape"] == [3, 3, 3]
    npz = np.load(out["matrices_file"])
    assert npz["matrices"].shape == (3, 3, 3)


# --------------------------------------------------------------------------
# Input-parsing robustness
# --------------------------------------------------------------------------

def test_load_supports_json_artifact(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    n = 8
    t = (np.arange(n, dtype="float64") + 1_600_000_000.0)
    payload = {"time": t.tolist(), "x": [1.0] * n, "y": [2.0] * n, "z": [3.0] * n}
    jpath = tmp_path / "vec.json"
    jpath.write_text(json.dumps(payload), encoding="utf-8")
    out = coords.transform_timeseries_coordinates(
        input_file=str(jpath),
        coord_in="gse",
        coord_out="gsm",
        output_file=str(tmp_path / "out.json"),
        vector_cols=["x", "y", "z"],
    )
    assert out["status"] == "success"
    assert out["rows"] == n


def test_load_rejects_missing_vector_cols(vector_csv, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = coords.transform_timeseries_coordinates(
        input_file=str(vector_csv),
        coord_in="gse",
        coord_out="gsm",
        output_file=str(tmp_path / "out.csv"),
        vector_cols=["bx", "by", "missing"],
    )
    assert out["status"] == "error"
    assert "missing" in out["message"]


def test_load_missing_file(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = coords.transform_timeseries_coordinates(
        input_file=str(tmp_path / "nope.csv"),
        coord_in="gse",
        coord_out="gsm",
        output_file=str(tmp_path / "out.csv"),
    )
    assert out["status"] == "error"
    assert "does not exist" in out["message"]


# --------------------------------------------------------------------------
# Opt-in real pyspedas round-trip (skips without the [analysis] extra)
# --------------------------------------------------------------------------

def _have_pyspedas() -> bool:
    try:
        importlib.import_module("pyspedas")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_pyspedas(), reason="requires spedas-mcp[analysis] (pyspedas)")
def test_real_minvar_eigenvalue_ordering(tmp_path):
    """Real backend: a planar discontinuity yields descending eigenvalues and a
    well-defined minimum-variance normal."""
    rng = np.random.default_rng(0)
    n = 500
    t = np.arange(n, dtype="float64")
    # Large variance along x, medium along y, tiny along z (the normal).
    data = np.column_stack([
        10.0 * np.sin(t / 20.0) + rng.normal(0, 0.5, n),
        3.0 * np.cos(t / 15.0) + rng.normal(0, 0.5, n),
        rng.normal(0, 0.05, n),
    ])
    df = pd.DataFrame({"time": t, "x": data[:, 0], "y": data[:, 1], "z": data[:, 2]})
    csv = tmp_path / "disc.csv"
    df.to_csv(csv, index=False)
    out = coords.analyze_minvar_coordinates(
        input_file=str(csv), output_dir=str(tmp_path / "mva"),
        vector_cols=["x", "y", "z"],
    )
    assert out["status"] == "success"
    lam = out["eigenvalues"]
    assert lam[0] >= lam[1] >= lam[2]
    # The minimum-variance direction should be close to +/- z.
    assert abs(out["normal_vector"][2]) > 0.9
