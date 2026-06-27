"""Offline tests for the magnetic-field-model / L-shell tools (issues #16, #17).

Like ``test_analysis_spectral.py``, these run without network access and without
a real ``pyspedas`` (geopack) install:

- Argument validation (unsupported model/trace, parameter-required gating,
  invalid shapes) happens before / independently of the backend and is checked
  directly.
- The "optional analysis extra missing" guard is verified by forcing the
  ``pyspedas`` import to fail.
- The positions-loading, file-out, summary-stat, and tracing logic is exercised
  against a lightweight fake ``pyspedas`` + fake ``pyspedas.geopack`` that mimics
  the tplot-variable store/get contract the real geopack wrappers use.

A real-backend round-trip is provided as an opt-in test that skips when the
``[analysis]`` extra is not installed.
"""
from __future__ import annotations

import builtins
import importlib.util
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from spedas_mcp.analysis import fieldmodels


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def positions_npz(tmp_path: Path) -> Path:
    """A small Nx3 GSM positions .npz (km) with an explicit times array."""
    n = 8
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    # Positions a few Re out, in km.
    base = np.array([5.0, 1.0, 0.5]) * fieldmodels.R_E_KM
    positions = np.outer(np.linspace(1.0, 1.5, n), base)
    path = tmp_path / "pos.npz"
    np.savez(path, positions=positions, times=t)
    return path


@pytest.fixture
def positions_npy(tmp_path: Path) -> Path:
    """A bare Nx3 .npy positions array (no times)."""
    positions = np.tile(np.array([4.0, 0.0, 0.0]) * fieldmodels.R_E_KM, (5, 1))
    path = tmp_path / "pos.npy"
    np.save(path, positions)
    return path


class _FakeTplotStore:
    """Minimal in-memory tplot variable store for the fake backend."""

    def __init__(self) -> None:
        self.data: dict[str, dict] = {}

    def store(self, name, data=None, **_):
        # Faithfully mimic the real pyspedas store_data, which scrubs non-finite
        # timestamps *in place* (``times[cond] = 0``). A read-only array (e.g. a
        # single-column ``df[...].to_numpy()`` view) raises here, reproducing
        # issue #58 in the offline suite rather than only against a live backend.
        x = np.asarray(data["x"])
        if np.issubdtype(x.dtype, np.floating):
            x[np.logical_not(np.isfinite(x))] = 0
        self.data[name] = {"x": x, "y": np.asarray(data["y"])}
        return True

    def get(self, name, **_):
        if name not in self.data:
            return None
        entry = self.data[name]
        nt = types.SimpleNamespace(times=entry["x"], y=entry["y"])
        return nt

    def delete(self, name, **_):
        self.data.pop(name, None)


def _install_fake_pyspedas(monkeypatch, *, trace_returns_foot=True, b_scale=100.0):
    """Install a fake ``pyspedas`` + ``pyspedas.geopack`` into sys.modules.

    The fake field models write a deterministic B field (magnitude tied to
    ``b_scale`` / position) and the fake tracer writes a foot point at a fixed
    fraction of the input position so L-shell math is exercised end-to-end.
    """
    store = _FakeTplotStore()

    pyspedas = types.ModuleType("pyspedas")
    geopack = types.ModuleType("pyspedas.geopack")

    pyspedas.store_data = store.store
    pyspedas.get_data = store.get
    pyspedas.del_data = store.delete
    pyspedas.set_coords = lambda *a, **k: None
    pyspedas.set_units = lambda *a, **k: None

    def _make_b(pos_var, suffix_stored):
        entry = store.data[pos_var]
        pos = entry["y"]
        # Deterministic dipole-ish field: magnitude scales with b_scale and 1/r.
        r = np.linalg.norm(pos, axis=1, keepdims=True) / fieldmodels.R_E_KM
        b = b_scale * pos / np.where(r == 0, 1.0, r**3)
        out = pos_var + suffix_stored
        store.store(out, data={"x": entry["x"], "y": b})
        return out

    def tigrf(pos_var, suffix=""):
        # Mirror the upstream quirk: store under _btigrf, return _igrf name.
        _make_b(pos_var, "_btigrf" + suffix)
        return pos_var + "_igrf" + suffix

    def tt89(pos_var, suffix="", **kw):
        return _make_b(pos_var, "_bt89" + suffix)

    def tt96(pos_var, suffix="", **kw):
        return _make_b(pos_var, "_bt96" + suffix)

    def tt01(pos_var, suffix="", **kw):
        return _make_b(pos_var, "_bt01" + suffix)

    def tts04(pos_var, suffix="", **kw):
        return _make_b(pos_var, "_bts04" + suffix)

    def ttrace2endpoint(tvar, model_str, endpoint, foot_name=None, km=True, **kw):
        if not trace_returns_foot:
            return None
        entry = store.data[tvar]
        pos = entry["y"]
        if endpoint == "equator":
            # Apex at a fixed radius scaled from the input radius (toward 6 Re).
            r = np.linalg.norm(pos, axis=1, keepdims=True)
            unit = pos / np.where(r == 0, 1.0, r)
            foot = unit * (6.0 * fieldmodels.R_E_KM)
        else:  # ionosphere-north / -south
            foot = pos * 0.2
        store.store(foot_name, data={"x": entry["x"], "y": foot})
        return foot_name

    geopack.tigrf = tigrf
    geopack.tt89 = tt89
    geopack.tt96 = tt96
    geopack.tt01 = tt01
    geopack.tts04 = tts04
    geopack.ttrace2endpoint = ttrace2endpoint

    monkeypatch.setitem(sys.modules, "pyspedas", pyspedas)
    monkeypatch.setitem(sys.modules, "pyspedas.geopack", geopack)

    # Register fake per-symbol submodules so _resolve_geopack's module-first
    # import (importlib.import_module("pyspedas.geopack.<mod>")) returns the
    # fakes rather than the real installed submodules when a real pyspedas is
    # present in the environment (e.g. the anaconda interpreter).
    submodule_symbols = {
        "igrf": {"tigrf": tigrf},
        "t89": {"tt89": tt89},
        "t96": {"tt96": tt96},
        "t01": {"tt01": tt01},
        "ts04": {"tts04": tts04},
        "ttrace2endpoint": {"ttrace2endpoint": ttrace2endpoint},
    }
    for mod_name, attrs in submodule_symbols.items():
        sub = types.ModuleType(f"pyspedas.geopack.{mod_name}")
        for attr, fn in attrs.items():
            setattr(sub, attr, fn)
        monkeypatch.setitem(sys.modules, f"pyspedas.geopack.{mod_name}", sub)
    return store


# --------------------------------------------------------------------------
# Validation (no backend needed)
# --------------------------------------------------------------------------

def test_eval_rejects_unknown_model(positions_npz, tmp_path):
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="dipole",
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "supported_models" in out


def test_eval_rejects_unknown_trace(positions_npz, tmp_path):
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
        trace="magnetopause",
    )
    assert out["status"] == "error"
    assert "supported_trace" in out


def test_eval_t89_without_index_requires_parameters(positions_npz, tmp_path):
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="t89",
    )
    assert out["status"] == "error"
    assert out["code"] == "parameters_required"
    assert out["required_one_of"] == ["iopt", "kp", "parmod"]


def test_eval_t96_without_params_requires_parameters(positions_npz, tmp_path):
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="t96",
    )
    assert out["status"] == "error"
    assert out["code"] == "parameters_required"
    assert set(out["missing"]) == {"pdyn", "dst", "byimf", "bzimf"}


def test_lshell_distorted_model_without_params_requires_parameters(positions_npz, tmp_path):
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l.npz"),
        model="ts04",
    )
    assert out["status"] == "error"
    assert out["code"] == "parameters_required"
    assert "w6" in out["required"]


def test_eval_bad_positions_shape(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    bad = tmp_path / "bad.npz"
    np.savez(bad, positions=np.zeros((4, 2)))  # not Nx3
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(bad),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert "N, 3" in out["message"] or "(N, 3)" in out["message"]


def test_eval_missing_positions_key(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    bad = tmp_path / "nopos.npz"
    np.savez(bad, foo=np.zeros((4, 3)))
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(bad),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert "positions" in out["message"]


def test_eval_times_length_mismatch(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    bad = tmp_path / "mismatch.npz"
    np.savez(bad, positions=np.zeros((4, 3)), times=np.zeros(3))
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(bad),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert "times length" in out["message"]


# --------------------------------------------------------------------------
# Missing-extra guard
# --------------------------------------------------------------------------

def test_eval_missing_pyspedas(positions_npz, tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas" or name.startswith("pyspedas."):
            raise ModuleNotFoundError("No module named 'pyspedas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"
    assert "spedas-mcp[analysis]" in out["message"]


def test_lshell_missing_pyspedas(positions_npz, tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas" or name.startswith("pyspedas."):
            raise ModuleNotFoundError("No module named 'pyspedas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l.npz"),
    )
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"


# --------------------------------------------------------------------------
# Logic with fake backend
# --------------------------------------------------------------------------

def test_eval_igrf_writes_artifact_and_summary(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "b_igrf.npz"
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(out_file),
        model="igrf",
    )
    assert out["status"] == "success"
    assert out["model"] == "igrf"
    assert out["trace"] == "none"
    assert out["n_samples"] == 8
    fs = out["field_strength_nT"]
    assert fs["min"] <= fs["mean"] <= fs["max"]
    assert "components" in fs
    assert "footpoints_file" not in out
    assert "lshell_summary" not in out
    assert out_file.exists()
    npz = np.load(out_file)
    assert npz["b_gsm"].shape == (8, 3)
    assert npz["positions"].shape == (8, 3)
    assert "time" in npz
    assert "footpoints_gsm" not in npz


def test_eval_npy_input_synthesizes_times(positions_npy, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npy),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "success"
    assert out["n_samples"] == 5


def test_eval_t89_with_iopt_succeeds(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b_t89.npz"),
        model="t89",
        parameters={"iopt": 2},
    )
    assert out["status"] == "success"
    assert out["model"] == "t89"


def test_eval_equator_trace_adds_lshell_summary(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "b_trace.npz"
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(out_file),
        model="igrf",
        trace="equator",
    )
    assert out["status"] == "success"
    assert out["trace"] == "equator"
    assert "footpoints_summary" in out
    assert "lshell_summary" in out
    # Fake tracer puts the apex at 6 Re, so mean L ~ 6.
    assert out["lshell_summary"]["mean_L"] == pytest.approx(6.0, rel=1e-6)
    npz = np.load(out_file)
    assert "footpoints_gsm" in npz
    assert "lshell" in npz


def test_eval_ionosphere_trace_no_lshell(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b_iono.npz"),
        model="igrf",
        trace="ionosphere",
    )
    assert out["status"] == "success"
    assert "footpoints_summary" in out
    assert "lshell_summary" not in out


def test_lshell_igrf_writes_artifact_and_summary(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "lshell.npz"
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(out_file),
        model="igrf",
    )
    assert out["status"] == "success"
    assert out["model"] == "igrf"
    s = out["summary"]
    assert s["min_L"] <= s["mean_L"] <= s["max_L"]
    assert s["mean_L"] == pytest.approx(6.0, rel=1e-6)
    assert "footprint_file" not in out
    npz = np.load(out_file)
    assert npz["lshell"].shape == (8,)
    assert "equatorial_foot_gsm" in npz
    assert "ionospheric_footprint_gsm" not in npz


def test_lshell_footprint_writes_footprint(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out_file = tmp_path / "lshell_fp.npz"
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(out_file),
        model="igrf",
        footprint=True,
    )
    assert out["status"] == "success"
    assert "footprint_file" in out
    assert "footprint_summary" in out
    npz = np.load(out_file)
    assert "ionospheric_footprint_gsm" in npz


def test_lshell_t96_with_params_succeeds(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l_t96.npz"),
        model="t96",
        geomag_parameters={"pdyn": 2.0, "dst": -10.0, "byimf": 0.0, "bzimf": -2.0},
    )
    assert out["status"] == "success"
    assert out["model"] == "t96"


def test_lshell_backend_returns_no_foot(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch, trace_returns_foot=False)
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert out["code"] == "backend_error"


# --------------------------------------------------------------------------
# parameters= alias for geomag_parameters= (calculate_lshell)
# --------------------------------------------------------------------------

def test_lshell_parameters_alias_is_accepted(positions_npz, tmp_path, monkeypatch):
    # The 'parameters' alias drives the distorted-model gate exactly like
    # 'geomag_parameters' (t96 here succeeds because the indices are supplied).
    _install_fake_pyspedas(monkeypatch)
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l_alias.npz"),
        model="t96",
        parameters={"pdyn": 2.0, "dst": -10.0, "byimf": 0.0, "bzimf": -2.0},
    )
    assert out["status"] == "success"
    assert out["model"] == "t96"


def test_lshell_parameters_alias_gates_missing(positions_npz, tmp_path):
    # Neither alias provided for a distorted model -> parameters_required
    # (no backend needed; the gate fires before any import).
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l.npz"),
        model="t96",
    )
    assert out["status"] == "error"
    assert out["code"] == "parameters_required"


def test_lshell_both_params_same_value_ok(positions_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    params = {"pdyn": 2.0, "dst": -10.0, "byimf": 0.0, "bzimf": -2.0}
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l_both.npz"),
        model="t96",
        geomag_parameters=params,
        parameters=dict(params),  # equal value, different object
    )
    assert out["status"] == "success"


def test_lshell_both_params_conflict_rejected(positions_npz, tmp_path):
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l.npz"),
        model="t96",
        geomag_parameters={"pdyn": 2.0, "dst": -10.0, "byimf": 0.0, "bzimf": -2.0},
        parameters={"pdyn": 5.0, "dst": -20.0, "byimf": 0.0, "bzimf": -5.0},
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "geomag_parameters" in out["message"]


def test_lshell_geomag_parameters_still_works(positions_npz, tmp_path, monkeypatch):
    # Backward compatibility: the original keyword keeps working unchanged.
    _install_fake_pyspedas(monkeypatch)
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l_bc.npz"),
        model="igrf",
        geomag_parameters=None,
    )
    assert out["status"] == "success"


def test_eval_csv_positions(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    import pandas as pd

    n = 6
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame(
        {
            "time": t,
            "x": np.full(n, 4.0 * fieldmodels.R_E_KM),
            "y": np.zeros(n),
            "z": np.zeros(n),
        }
    )
    csv = tmp_path / "pos.csv"
    df.to_csv(csv, index=False)
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(csv),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "success"
    assert out["n_samples"] == 6


def test_load_positions_csv_returns_writeable_times(tmp_path):
    """Regression for issue #58: a single-column ``df[time].to_numpy()`` view is
    read-only, and pyspedas ``store_data`` writes into the time array in place.
    ``_load_positions`` must hand back writeable, owned arrays so the backend's
    in-place non-finite scrub does not raise ``assignment destination is
    read-only``.
    """
    import pandas as pd

    n = 4
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame(
        {
            "time": t,
            "x": np.full(n, 4.0 * fieldmodels.R_E_KM),
            "y": np.zeros(n),
            "z": np.zeros(n),
        }
    )
    csv = tmp_path / "pos.csv"
    df.to_csv(csv, index=False)
    times, positions = fieldmodels._load_positions(
        str(csv), position_cols=["x", "y", "z"]
    )
    assert times.flags.writeable
    assert positions.flags.writeable
    # The exact in-place write the real store_data performs must not raise.
    times[np.logical_not(np.isfinite(times))] = 0


def test_lshell_csv_input_survives_inplace_time_scrub(tmp_path, monkeypatch):
    """Regression for issue #58 against the (now faithful) fake store_data, which
    scrubs non-finite timestamps in place. Without the loader copy, calling
    calculate_lshell with a CSV positions file raised ``assignment destination is
    read-only``.
    """
    _install_fake_pyspedas(monkeypatch)
    import pandas as pd

    n = 5
    t = np.arange(n, dtype="float64") + 1_600_000_000.0
    df = pd.DataFrame(
        {
            "time": t,
            "x": np.full(n, 5.0 * fieldmodels.R_E_KM),
            "y": np.zeros(n),
            "z": np.zeros(n),
        }
    )
    csv = tmp_path / "pos.csv"
    df.to_csv(csv, index=False)
    out = fieldmodels.calculate_lshell(
        positions_file=str(csv),
        output_file=str(tmp_path / "l.npz"),
        model="igrf",
        position_cols=["x", "y", "z"],
    )
    assert out["status"] == "success", out


# --------------------------------------------------------------------------
# Outdated-backend guard (older pyspedas missing the required geopack APIs)
# --------------------------------------------------------------------------

def _install_partial_geopack(monkeypatch):
    """Install a fake pyspedas whose geopack lacks ttrace2endpoint / tigrf.

    Mirrors the older installed pyspedas that exposes tt89/tt96/tt01/tts04 but
    not the modern tracing / IGRF entry points (and no per-model submodules to
    import them from).
    """
    store = _FakeTplotStore()
    pyspedas = types.ModuleType("pyspedas")
    geopack = types.ModuleType("pyspedas.geopack")
    pyspedas.store_data = store.store
    pyspedas.get_data = store.get
    pyspedas.del_data = store.delete
    pyspedas.set_coords = lambda *a, **k: None
    pyspedas.set_units = lambda *a, **k: None
    # Only the older subset of model wrappers exists; tigrf + ttrace2endpoint and
    # the per-model submodules are absent.
    geopack.tt89 = lambda *a, **k: "x"
    geopack.tt96 = lambda *a, **k: "x"
    geopack.tt01 = lambda *a, **k: "x"
    geopack.tts04 = lambda *a, **k: "x"
    monkeypatch.setitem(sys.modules, "pyspedas", pyspedas)
    monkeypatch.setitem(sys.modules, "pyspedas.geopack", geopack)
    # Ensure the per-model submodule import paths fail (older layout).
    for sub in ("igrf", "ttrace2endpoint"):
        monkeypatch.delitem(sys.modules, f"pyspedas.geopack.{sub}", raising=False)
    return store


def test_eval_igrf_outdated_geopack(positions_npz, tmp_path, monkeypatch):
    _install_partial_geopack(monkeypatch)
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert out["code"] == "backend_outdated"
    assert "tigrf" in out["missing"]
    assert "update" in out["message"].lower()


def test_eval_t89_trace_outdated_geopack(positions_npz, tmp_path, monkeypatch):
    # T89 model exists in the old backend, but tracing to the equator needs
    # ttrace2endpoint, which does not -> backend_outdated.
    _install_partial_geopack(monkeypatch)
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "b.npz"),
        model="t89",
        parameters={"iopt": 2},
        trace="equator",
    )
    assert out["status"] == "error"
    assert out["code"] == "backend_outdated"
    assert "ttrace2endpoint" in out["missing"]


def test_lshell_outdated_geopack(positions_npz, tmp_path, monkeypatch):
    _install_partial_geopack(monkeypatch)
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "l.npz"),
        model="igrf",
    )
    assert out["status"] == "error"
    assert out["code"] == "backend_outdated"
    assert "ttrace2endpoint" in out["missing"]


# --------------------------------------------------------------------------
# Optional real-backend round-trip (skips unless the SPECIFIC geopack APIs are
# importable, not merely because the pyspedas package exists -- an older
# pyspedas without ttrace2endpoint must still let the normal suite pass).
# --------------------------------------------------------------------------

def _real_geopack_available() -> bool:
    """True only if a real pyspedas with the required geopack APIs is importable."""
    if importlib.util.find_spec("pyspedas") is None:
        return False
    try:
        from spedas_mcp.analysis.fieldmodels import _resolve_geopack

        _resolve_geopack(["tigrf", "ttrace2endpoint"])
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _real_geopack_available(),
    reason="requires a pyspedas with geopack tigrf + ttrace2endpoint APIs",
)
def test_lshell_real_backend_roundtrip(positions_npz, tmp_path):  # pragma: no cover
    out = fieldmodels.calculate_lshell(
        positions_file=str(positions_npz),
        output_file=str(tmp_path / "lshell_real.npz"),
        model="igrf",
    )
    assert out["status"] == "success"
    npz = np.load(tmp_path / "lshell_real.npz")
    assert npz["lshell"].shape[0] == 8
    assert np.isfinite(npz["lshell"]).any()


def _equatorial_positions_npz(tmp_path: Path, radii_re) -> Path:
    """Write GSM-equatorial-plane (z=0) positions at the given radii (Re), in km."""
    radii_re = np.asarray(radii_re, dtype="float64")
    n = radii_re.shape[0]
    positions = np.zeros((n, 3), dtype="float64")
    positions[:, 0] = radii_re * fieldmodels.R_E_KM  # along +X_GSM, on the equator
    t = np.arange(n, dtype="float64") + 1_577_836_800.0  # 2020-01-01, IGRF-valid epoch
    path = tmp_path / "equ_pos.npz"
    np.savez(path, positions=positions, times=t)
    return path


@pytest.mark.skipif(
    not _real_geopack_available(),
    reason="requires a pyspedas with geopack tigrf + ttrace2endpoint APIs",
)
def test_lshell_real_backend_numeric(tmp_path):  # pragma: no cover
    # For dipole-dominated IGRF, a field line starting on the magnetic equator
    # has its apex at (approximately) its starting radius, so L ~= r/Re. The
    # geomagnetic dipole is tilted/offset from GSM, so use a generous tolerance
    # rather than an exact equality -- this is a sanity bound, not a precise ref.
    radii = [3.0, 4.0, 5.0, 6.0]
    pos = _equatorial_positions_npz(tmp_path, radii)
    out = fieldmodels.calculate_lshell(
        positions_file=str(pos),
        output_file=str(tmp_path / "lshell_num.npz"),
        model="igrf",
    )
    assert out["status"] == "success"
    npz = np.load(tmp_path / "lshell_num.npz")
    lshell = np.asarray(npz["lshell"], dtype="float64")
    assert lshell.shape == (len(radii),)
    assert np.isfinite(lshell).all()
    assert (lshell > 0).all()
    # L within +/-30% of the starting equatorial radius (Re), and monotone-ish:
    # larger starting radius -> larger L.
    for r, L in zip(radii, lshell):
        assert L == pytest.approx(r, rel=0.30), f"L={L} not within 30% of r={r}"
    assert lshell[-1] > lshell[0]
    # Summary stats are consistent with the per-sample series.
    assert out["summary"]["min_L"] == pytest.approx(float(lshell.min()), rel=1e-9)
    assert out["summary"]["max_L"] == pytest.approx(float(lshell.max()), rel=1e-9)


@pytest.mark.skipif(
    not _real_geopack_available(),
    reason="requires a pyspedas with geopack tigrf + ttrace2endpoint APIs",
)
def test_evaluate_magnetic_field_real_backend_igrf(tmp_path):  # pragma: no cover
    # IGRF B at equatorial positions: artifact contents, finite vectors, strictly
    # positive field strength (nT), and a falling magnitude with radius (dipole
    # |B| ~ 1/r^3 on the equator) as a defensible physical sanity check.
    radii = [3.0, 4.0, 5.0, 6.0]
    pos = _equatorial_positions_npz(tmp_path, radii)
    out_file = tmp_path / "b_real.npz"
    out = fieldmodels.evaluate_magnetic_field(
        positions_file=str(pos),
        output_file=str(out_file),
        model="igrf",
    )
    assert out["status"] == "success"
    assert out["model"] == "igrf"
    assert out["n_samples"] == len(radii)

    fs = out["field_strength_nT"]
    assert np.isfinite(fs["min"]) and np.isfinite(fs["max"]) and np.isfinite(fs["mean"])
    assert fs["min"] > 0.0  # |B| is strictly positive
    assert fs["min"] <= fs["mean"] <= fs["max"]

    npz = np.load(out_file)
    bvec = np.asarray(npz["b_gsm"], dtype="float64")
    assert bvec.shape == (len(radii), 3)
    assert np.isfinite(bvec).all()
    assert "positions" in npz and "time" in npz
    assert "footpoints_gsm" not in npz  # trace='none'

    strength = np.linalg.norm(bvec, axis=1)
    assert (strength > 0).all()
    # Dipole field magnitude falls with radius on the equator.
    assert strength[0] > strength[-1]
