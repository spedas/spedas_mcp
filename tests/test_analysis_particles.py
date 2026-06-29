"""Offline tests for the Phase-2 particle tools (issues #18, #19).

Like ``test_analysis_spectral.py``, these run without network access and without
relying on a particular ``pyspedas`` build:

- Argument validation happens before the backend import and is checked directly.
- The "optional analysis extra missing" guard is verified by forcing the import
  to fail.
- The "exact backend function absent" gate (Batch O lesson: package presence
  does not imply a given function exists) is verified by injecting a fake
  ``pyspedas`` tree with selected functions missing.
- The file-in / file-out, serialization, and summary logic is exercised against
  a lightweight fake ``pyspedas`` injected into ``sys.modules``.

Deterministic real-backend round-trips are provided as opt-in tests that skip
when the *exact* pyspedas particle functions are not importable.
"""
from __future__ import annotations

import builtins
import importlib
import inspect
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from spedas_agent_kit.analysis import particles


# --------------------------------------------------------------------------
# Synthetic distribution fixtures
# --------------------------------------------------------------------------

def _make_dist_arrays(n_time: int = 3, n_energy: int = 8, n_theta: int = 4, n_phi: int = 4):
    """Build a deterministic synthetic distribution matching the documented schema."""
    n_angle = n_theta * n_phi
    theta_vals = np.linspace(-67.5, 67.5, n_theta)
    phi_vals = np.linspace(22.5, 337.5, n_phi)
    th, ph = np.meshgrid(theta_vals, phi_vals, indexing="ij")
    theta_ang = th.reshape(-1)
    phi_ang = ph.reshape(-1)
    energy_vals = np.geomspace(10.0, 30000.0, n_energy)

    energy = np.repeat(energy_vals[:, None], n_angle, axis=1)
    theta = np.repeat(theta_ang[None, :], n_energy, axis=0)
    phi = np.repeat(phi_ang[None, :], n_energy, axis=0)
    dtheta = np.full((n_energy, n_angle), 45.0)
    dphi = np.full((n_energy, n_angle), 90.0)
    denergy = np.repeat((energy_vals * 0.3)[:, None], n_angle, axis=1)
    bins = np.ones((n_energy, n_angle))
    data = np.random.RandomState(0).rand(n_time, n_energy, n_angle) * 1e6
    times = 1_600_000_000.0 + np.arange(n_time, dtype="float64")
    return {
        "times": times,
        "data": data,
        "energy": energy,
        "denergy": denergy,
        "theta": theta,
        "dtheta": dtheta,
        "phi": phi,
        "dphi": dphi,
        "bins": bins,
        "magf": np.tile(np.array([0.0, 0.0, 5.0]), (n_time, 1)),
        "charge": 1.0,
        "mass": 5.68e-6,  # electron mass in pyspedas eV/(km/s)^2 units
    }


@pytest.fixture
def dist_npz(tmp_path: Path) -> Path:
    arrays = _make_dist_arrays()
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    return path


@pytest.fixture
def dist_json(tmp_path: Path) -> Path:
    arrays = _make_dist_arrays()
    payload = {
        k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in arrays.items()
    }
    path = tmp_path / "dist.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Fake pyspedas backend injection
# --------------------------------------------------------------------------

def _fake_moments_3d(data_in, sc_pot=0, no_unit_conversion=False):
    n_active = float(np.nansum(data_in["bins"]))
    return {
        "density": 1.0 + 0.001 * n_active,
        "flux": np.array([10.0, 20.0, 30.0]),
        "mftens": np.arange(6, dtype="float64"),
        "velocity": np.array([100.0, -50.0, 25.0]),
        "ptens": np.array([1.0, 2.0, 3.0, 0.1, 0.2, 0.3]),
        "ttens": np.diag([5.0, 6.0, 7.0]).astype("float64"),
        "vthermal": 42.0,
        "avgtemp": 6.0,
    }


def _fake_e_spec(data_in):
    e = np.asarray(data_in["energy"], dtype="float64")[:, 0]
    return e, np.ones(e.shape[0])


def _fake_phi_spec(data_in, resolution=None):
    n = resolution if resolution is not None else 4
    return np.linspace(0, 360, n), np.full(n, 2.0)


def _fake_theta_spec(data_in, resolution=None, colatitude=False):
    n = resolution if resolution is not None else 4
    # Echo the active-bin mean so colatitude (pitch-angle) calls produce a
    # non-trivial, data-dependent value the tests can assert on.
    val = float(np.nanmean(np.asarray(data_in["data"], dtype="float64")))
    lo, hi = (0, 180) if colatitude else (-90, 90)
    return np.linspace(lo, hi, n), np.full(n, val)


def _fake_do_fac(data_in, mat):
    """Minimal stand-in for spd_pgs_do_fac: applies the rotation to look dirs.

    Mirrors the real backend's contract (returns a copy with rotated
    theta/phi) closely enough for the tool's pitch-angle path to exercise the
    full code, while staying deterministic and dependency-free.
    """
    out = dict(data_in)
    theta = np.asarray(data_in["theta"], dtype="float64") * np.pi / 180.0
    phi = np.asarray(data_in["phi"], dtype="float64") * np.pi / 180.0
    x = np.cos(theta) * np.cos(phi)
    y = np.cos(theta) * np.sin(phi)
    z = np.sin(theta)
    xr = mat[0, 0] * x + mat[0, 1] * y + mat[0, 2] * z
    yr = mat[1, 0] * x + mat[1, 1] * y + mat[1, 2] * z
    zr = mat[2, 0] * x + mat[2, 1] * y + mat[2, 2] * z
    out["theta"] = np.arcsin(np.clip(zr, -1.0, 1.0)) * 180.0 / np.pi
    out["phi"] = np.arctan2(yr, xr) * 180.0 / np.pi
    return out


def _install_fake_pyspedas(monkeypatch, *, include_fac=True, **overrides):
    """Install a minimal fake ``pyspedas`` particle tree into sys.modules."""
    mods: dict[str, types.ModuleType] = {}

    def _mod(name: str) -> types.ModuleType:
        m = types.ModuleType(name)
        mods[name] = m
        return m

    pyspedas_mod = _mod("pyspedas")
    pyspedas_mod.get_data = overrides.get("get_data", lambda name: None)
    _mod("pyspedas.particles")
    _mod("pyspedas.particles.moments")
    _mod("pyspedas.particles.spd_part_products")

    moments_mod = _mod("pyspedas.particles.moments.moments_3d")
    moments_mod.moments_3d = overrides.get("moments_3d", _fake_moments_3d)

    e_mod = _mod("pyspedas.particles.spd_part_products.spd_pgs_make_e_spec")
    e_mod.spd_pgs_make_e_spec = overrides.get("e_spec", _fake_e_spec)

    phi_mod = _mod("pyspedas.particles.spd_part_products.spd_pgs_make_phi_spec")
    phi_mod.spd_pgs_make_phi_spec = overrides.get("phi_spec", _fake_phi_spec)

    theta_mod = _mod("pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec")
    theta_mod.spd_pgs_make_theta_spec = overrides.get("theta_spec", _fake_theta_spec)

    # spd_pgs_do_fac powers the pitch-angle FAC rotation. Present in every real
    # pyspedas build that has the spectra functions; inject it here unless a test
    # explicitly drops it to exercise the unsupported gate.
    if include_fac:
        fac_mod = _mod("pyspedas.particles.spd_part_products.spd_pgs_do_fac")
        fac_mod.spd_pgs_do_fac = overrides.get("do_fac", _fake_do_fac)

    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    if not include_fac:
        monkeypatch.delitem(
            sys.modules,
            "pyspedas.particles.spd_part_products.spd_pgs_do_fac",
            raising=False,
        )
    return mods


# --------------------------------------------------------------------------
# Validation (no backend needed)
# --------------------------------------------------------------------------

def test_moments_rejects_bad_output_format(dist_npz, tmp_path):
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), output_format="xml"
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "output_format" in out["message"]


def test_moments_rejects_bad_energy_range(dist_npz, tmp_path):
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), energy_range_ev=[100.0, 10.0]
    )
    assert out["status"] == "error"
    assert "energy_range_ev" in out["message"]


def test_moments_rejects_single_energy_bound(dist_npz, tmp_path):
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), energy_range_ev=[100.0]
    )
    assert out["status"] == "error"


def test_moments_missing_magf_is_structured_invalid_argument(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    arrays = _make_dist_arrays()
    arrays.pop("magf")
    dist = tmp_path / "dist_without_magf.npz"
    np.savez(dist, **arrays)

    out = particles.compute_particle_moments(str(dist), str(tmp_path / "mom"))

    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "magf" in out["message"]


def test_moments_accepts_single_magf_vector_broadcast(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    arrays = _make_dist_arrays()
    arrays["magf"] = np.array([0.0, 0.0, 5.0])
    dist = tmp_path / "dist_single_magf.npz"
    np.savez(dist, **arrays)

    out = particles.compute_particle_moments(str(dist), str(tmp_path / "mom"))

    assert out["status"] == "success"
    assert out["n_time"] == 3


def test_spectra_rejects_unknown_type(dist_npz, tmp_path):
    out = particles.compute_particle_spectra(
        str(dist_npz), str(tmp_path / "spec"), spectrum_types=["bogus"]
    )
    assert out["status"] == "error"
    assert "valid_spectrum_types" in out


def test_spectra_rejects_empty_types(dist_npz, tmp_path):
    out = particles.compute_particle_spectra(
        str(dist_npz), str(tmp_path / "spec"), spectrum_types=[]
    )
    assert out["status"] == "error"


def test_spectra_rejects_bad_resolution(dist_npz, tmp_path):
    out = particles.compute_particle_spectra(
        str(dist_npz), str(tmp_path / "spec"), spectrum_types=["phi"], resolution=0
    )
    assert out["status"] == "error"
    assert "resolution" in out["message"]


# --------------------------------------------------------------------------
# Missing-extra / missing-backend guards
# --------------------------------------------------------------------------

def test_moments_missing_pyspedas(dist_npz, tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas" or name.startswith("pyspedas."):
            raise ModuleNotFoundError("No module named 'pyspedas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = particles.compute_particle_moments(str(dist_npz), str(tmp_path / "mom"))
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"
    assert "spedas-agent-kit[analysis]" in out["message"]


def test_moments_backend_function_absent(dist_npz, tmp_path, monkeypatch):
    # pyspedas imports, but the moments_3d module lacks the function.
    mods = _install_fake_pyspedas(monkeypatch)
    del mods["pyspedas.particles.moments.moments_3d"].moments_3d

    out = particles.compute_particle_moments(str(dist_npz), str(tmp_path / "mom"))
    assert out["status"] == "error"
    assert out["code"] == "unsupported"


def test_spectra_missing_pyspedas(dist_npz, tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas" or name.startswith("pyspedas."):
            raise ModuleNotFoundError("No module named 'pyspedas'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    out = particles.compute_particle_spectra(str(dist_npz), str(tmp_path / "spec"))
    assert out["status"] == "error"
    assert out["code"] == "dependency_missing"


# --------------------------------------------------------------------------
# Logic with fake backends
# --------------------------------------------------------------------------

def test_moments_writes_json_artifact(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), output_format="json"
    )
    assert out["status"] == "success"
    assert out["n_time"] == 3
    assert out["output_format"] == "json"
    assert out["density_summary"]["mean"] > 0
    assert out["temperature_summary"]["mean"] == 6.0
    assert "trace" in out["pressure_tensor_summary"]
    # Artifact-first: full tensors are NOT inline.
    assert "ptens" not in out and "ttens" not in out
    path = Path(out["moments_file"])
    assert path.exists() and path.suffix == ".json"
    payload = json.loads(path.read_text())
    assert len(payload["density"]) == 3
    assert "pxy" in payload  # pressure-tensor off-diagonal preserved in artifact


def test_moments_writes_csv_artifact(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), output_format="csv"
    )
    assert out["status"] == "success"
    path = Path(out["moments_file"])
    assert path.exists() and path.suffix == ".csv"
    text = path.read_text()
    assert "density" in text.splitlines()[0]


def test_moments_writes_labels_sidecar(dist_npz, tmp_path, monkeypatch):
    # Issue #154: a self-describing units/labels sidecar is written next to the
    # moments artifact so a renderer / human can recover per-column units.
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), output_format="csv"
    )
    assert out["status"] == "success"
    sidecar = Path(out["labels_file"])
    assert sidecar.exists()
    moments_path = Path(out["moments_file"])
    # Convention: <artifact-name>.labels.json sibling of the artifact.
    assert sidecar.name == moments_path.name + ".labels.json"
    payload = json.loads(sidecar.read_text())
    cols = payload["columns"]
    # Known pyspedas moments_3d units are recoverable per column.
    assert cols["density"] == "cm^-3"
    assert cols["vx"] == "km/s" and cols["vy"] == "km/s" and cols["vz"] == "km/s"
    assert cols["avgtemp"] == "eV"
    assert cols["pxx"] == "eV/cm^3"
    # Multi-quantity artifact: a single misleading axis unit is intentionally
    # omitted while the descriptive axis_label is present.
    assert "axis_units" not in payload
    assert payload["axis_label"]


def test_moments_sidecar_units_flagged_for_no_unit_conversion(
    dist_npz, tmp_path, monkeypatch
):
    # When raw (no_unit_conversion) units are requested, the sidecar flags the
    # columns as raw instead of asserting physical units.
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(dist_npz),
        str(tmp_path / "mom"),
        output_format="json",
        no_unit_conversion=True,
    )
    assert out["status"] == "success"
    payload = json.loads(Path(out["labels_file"]).read_text())
    assert payload["columns"]["density"].startswith("raw")


def test_moments_sidecar_is_consumed_by_render_tplot(dist_npz, tmp_path, monkeypatch):
    # End-to-end: the sidecar written by compute_particle_moments is the same
    # convention render_tplot reads, so the moments line panel is self-describing.
    from spedas_agent_kit.analysis import plotting

    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "mom"), output_format="csv"
    )
    assert out["status"] == "success"

    labels = plotting._read_sidecar_labels(Path(out["moments_file"]))
    # render_tplot resolves a descriptive (non-stem) y-axis label from the
    # sidecar rather than the bare filename stem.
    assert labels.get("axis_label")
    panel = {"file": out["moments_file"], **labels}
    resolved = plotting._axis_ylabel(panel)
    assert resolved == labels["axis_label"]
    assert resolved != Path(out["moments_file"]).stem


def test_moments_energy_range_masks_bins(dist_npz, tmp_path, monkeypatch):
    # The fake moments_3d encodes the active-bin count into density, so a
    # narrower energy band must lower the active count and thus the density.
    _install_fake_pyspedas(monkeypatch)
    full = particles.compute_particle_moments(
        str(dist_npz), str(tmp_path / "full"), output_format="json"
    )
    banded = particles.compute_particle_moments(
        str(dist_npz),
        str(tmp_path / "banded"),
        energy_range_ev=[100.0, 5000.0],
        output_format="json",
    )
    assert full["status"] == "success" and banded["status"] == "success"
    assert banded["density_summary"]["mean"] < full["density_summary"]["mean"]
    assert banded["energy_range_ev"] == [100.0, 5000.0]


def test_moments_accepts_json_input(dist_json, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(dist_json), str(tmp_path / "mom"), output_format="json"
    )
    assert out["status"] == "success"
    assert out["n_time"] == 3


def test_spectra_writes_npz_per_type(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["energy", "azimuth", "elevation"],
    )
    assert out["status"] == "success"
    assert set(out["succeeded"]) == {"energy", "phi", "theta"}
    expected_units = {"energy": "eV", "phi": "deg", "theta": "deg"}
    for stype in ("energy", "phi", "theta"):
        entry = out["spectra"][stype]
        assert entry["status"] == "success"
        spec = Path(entry["spectrogram_file"])
        assert spec.exists()
        npz = np.load(spec)
        assert npz["spectrogram"].shape[0] == 3  # n_time
        assert "time" in npz and "axis" in npz
        assert entry["shape"][0] == 3
        # Issue #150: the .npz is self-describing so render_tplot can label the
        # y-axis/colorbar without falling back to the filename stem.
        assert str(npz["axis_label"]) == stype
        assert str(npz["axis_units"]) == expected_units[stype]
        assert str(npz["value_label"]) == "flux"


def test_spectra_resolution_controls_bins(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["phi"],
        resolution=9,
    )
    assert out["status"] == "success"
    assert out["spectra"]["phi"]["shape"][1] == 9


def _mag_npz(tmp_path: Path, n_time: int = 3, b=None) -> Path:
    """Write a (T,3) B-field reference matching the synthetic distribution."""
    if b is None:
        b = np.tile(np.array([0.0, 0.0, 1.0]), (n_time, 1))
    path = tmp_path / "mag.npz"
    np.savez(path, times=np.arange(float(n_time)), b=np.asarray(b, dtype="float64"))
    return path


@pytest.fixture
def dist_npz_no_magf(tmp_path: Path) -> Path:
    """A distribution artifact that carries NO embedded magf (issue #148).

    This is the genuine 'no B reference anywhere' case: with neither an embedded
    magf nor a mag_file, the pitch-angle entry must report needs_input.
    """
    arrays = _make_dist_arrays()
    arrays.pop("magf")
    path = tmp_path / "dist_no_magf.npz"
    np.savez(path, **arrays)
    return path


def test_pitch_angle_needs_input_when_no_mag_anywhere(dist_npz_no_magf, tmp_path, monkeypatch):
    # No embedded magf AND no mag_file -> needs_input (the call still succeeds for
    # the other requested spectra). mag_source records the missing reference.
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_spectra(
        str(dist_npz_no_magf),
        str(tmp_path / "spec"),
        spectrum_types=["energy", "pitch_angle"],
    )
    assert out["status"] == "success"
    entry = out["spectra"]["pitch_angle"]
    assert entry["status"] == "needs_input"
    assert entry["mag_source"] == "missing"
    assert "energy" in out["succeeded"]


def test_pitch_angle_uses_embedded_magf_without_mag_file(dist_npz, tmp_path, monkeypatch):
    # Issue #148: a distribution artifact carrying embedded (T,3) magf produces a
    # PAD with NO separate mag_file. Provenance records the embedded source.
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
    )
    assert out["status"] == "success"
    entry = out["spectra"]["pitch_angle"]
    assert entry["status"] == "success"
    assert entry["mag_source"] == "distribution_artifact_magf"
    assert entry["shape"] == [3, 18]
    spec = np.load(entry["spectrogram_file"])
    assert spec["spectrogram"].shape == (3, 18)
    assert np.isfinite(spec["spectrogram"]).all()
    # Issue #150: the PAD .npz carries axis label/units (deg, 0-180) and a flux
    # (z) label so render_tplot can label the pitch-angle axis and colorbar.
    assert str(spec["axis_label"]) == "pitch_angle"
    assert str(spec["axis_units"]) == "deg"
    assert str(spec["value_label"]) == "flux"


def test_pitch_angle_single_embedded_magf_vector_broadcast(tmp_path, monkeypatch):
    # A single (3,) embedded magf is normalized to (T,3) and still drives the PAD
    # via the embedded-magf path (no mag_file).
    _install_fake_pyspedas(monkeypatch)
    arrays = _make_dist_arrays()
    arrays["magf"] = np.array([0.0, 0.0, 5.0])
    dist = tmp_path / "dist_single_embedded_magf.npz"
    np.savez(dist, **arrays)
    out = particles.compute_particle_spectra(
        str(dist),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
    )
    assert out["status"] == "success"
    entry = out["spectra"]["pitch_angle"]
    assert entry["status"] == "success"
    assert entry["mag_source"] == "distribution_artifact_magf"
    assert entry["shape"][0] == 3


def test_pitch_angle_mag_file_overrides_embedded_magf(dist_npz, tmp_path, monkeypatch):
    # Issue #148 requirement 3: an explicit mag_file wins over embedded magf.
    # The two B references point along different axes; both fakes succeed, so the
    # discriminator is the recorded provenance (mag_source == 'mag_file').
    _install_fake_pyspedas(monkeypatch)
    # dist_npz embeds magf = [0,0,5]; supply a mag_file along a different axis.
    mag = _mag_npz(tmp_path, b=np.tile(np.array([1.0, 0.0, 0.0]), (3, 1)))
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["status"] == "success"
    entry = out["spectra"]["pitch_angle"]
    assert entry["status"] == "success"
    assert entry["mag_source"] == "mag_file"


def test_pitch_angle_success_with_mag_file(dist_npz, tmp_path, monkeypatch):
    # With a valid mag_file the FAC pitch-angle path computes and writes an
    # artifact spanning 0-180 deg (the honest #19 deliverable).
    _install_fake_pyspedas(monkeypatch)
    mag = _mag_npz(tmp_path)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["status"] == "success"
    entry = out["spectra"]["pitch_angle"]
    assert entry["status"] == "success"
    assert entry["mag_source"] == "mag_file"
    assert entry["axis_label"] == "pitch_angle"
    assert entry["axis_units"] == "deg"
    # Default 18 bins over 0-180 deg.
    assert entry["n_pitch_angle_bins"] == 18
    assert entry["shape"] == [3, 18]
    lo, hi = entry["axis_range"]
    assert lo >= 0.0 and hi <= 180.0
    spec = np.load(entry["spectrogram_file"])
    assert spec["spectrogram"].shape == (3, 18)
    assert np.isfinite(spec["spectrogram"]).all()


def test_pitch_angle_resolution_controls_bins(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    mag = _mag_npz(tmp_path)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
        resolution=12,
    )
    assert out["status"] == "success"
    assert out["spectra"]["pitch_angle"]["shape"][1] == 12
    assert out["spectra"]["pitch_angle"]["n_pitch_angle_bins"] == 12


def test_pitch_angle_single_b_vector_broadcast(dist_npz, tmp_path, monkeypatch):
    # A single (3,) B vector is broadcast across all distribution slices.
    _install_fake_pyspedas(monkeypatch)
    mag = tmp_path / "mag.npz"
    np.savez(mag, b=np.array([0.0, 0.0, 1.0]))
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["status"] == "success"
    assert out["spectra"]["pitch_angle"]["shape"][0] == 3


def test_pitch_angle_mag_missing_file(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(tmp_path / "nope.npz"),
    )
    assert out["spectra"]["pitch_angle"]["status"] == "error"
    assert "does not exist" in out["spectra"]["pitch_angle"]["message"]


def test_pitch_angle_mag_missing_b_field(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    mag = tmp_path / "mag.npz"
    np.savez(mag, times=np.arange(3.0))  # no 'b'
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["spectra"]["pitch_angle"]["status"] == "error"
    assert "'b'" in out["spectra"]["pitch_angle"]["message"]


def test_pitch_angle_mag_time_mismatch(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    mag = tmp_path / "mag.npz"
    np.savez(mag, b=np.ones((5, 3)))  # 5 != 3 distribution slices
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["spectra"]["pitch_angle"]["status"] == "error"
    assert "time samples" in out["spectra"]["pitch_angle"]["message"]


def test_pitch_angle_zero_b_vector_rejected(dist_npz, tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    mag = tmp_path / "mag.npz"
    np.savez(mag, b=np.zeros((3, 3)))  # no defined direction
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["spectra"]["pitch_angle"]["status"] == "error"
    assert "zero" in out["spectra"]["pitch_angle"]["message"].lower()


def test_pitch_angle_unsupported_when_fac_absent(dist_npz, tmp_path, monkeypatch):
    # do_fac backend absent -> unsupported (structured), not a crash.
    _install_fake_pyspedas(monkeypatch, include_fac=False)
    mag = _mag_npz(tmp_path)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
    )
    assert out["spectra"]["pitch_angle"]["status"] == "unsupported"
    assert out["spectra"]["pitch_angle"]["mag_source"] == "mag_file"
    assert out["status"] == "error"


def test_pitch_angle_with_energy_combined(dist_npz, tmp_path, monkeypatch):
    # energy + pitch_angle together: both succeed, overall success.
    _install_fake_pyspedas(monkeypatch)
    mag = _mag_npz(tmp_path)
    out = particles.compute_particle_spectra(
        str(dist_npz),
        str(tmp_path / "spec"),
        spectrum_types=["energy", "pitch_angle"],
        mag_file=str(mag),
    )
    assert out["status"] == "success"
    assert set(out["succeeded"]) == {"energy", "pitch_angle"}


# --------------------------------------------------------------------------
# Distribution-schema robustness
# --------------------------------------------------------------------------

def test_missing_distribution_file(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.compute_particle_moments(
        str(tmp_path / "nope.npz"), str(tmp_path / "mom")
    )
    assert out["status"] == "error"
    assert "does not exist" in out["message"]


def test_missing_required_field(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    # Drop 'charge' (required by moments) from an otherwise-valid distribution.
    arrays = _make_dist_arrays()
    del arrays["charge"]
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    out = particles.compute_particle_moments(str(path), str(tmp_path / "mom"))
    assert out["status"] == "error"
    assert "charge" in out["message"]


def test_single_slice_broadcast(tmp_path, monkeypatch):
    # A 2D (E,A) 'data' is treated as a single time slice.
    _install_fake_pyspedas(monkeypatch)
    arrays = _make_dist_arrays(n_time=1)
    arrays["data"] = arrays["data"][0]  # (E,A)
    del arrays["times"]
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    out = particles.compute_particle_moments(
        str(path), str(tmp_path / "mom"), output_format="json"
    )
    assert out["status"] == "success"
    assert out["n_time"] == 1


def test_2d_slice_field_broadcast_across_time(tmp_path, monkeypatch):
    # Per-slice geometry given once as (E,A) is broadcast across all time slices.
    _install_fake_pyspedas(monkeypatch)
    arrays = _make_dist_arrays(n_time=3)
    # energy/theta/etc are already (E,A); data is (T,E,A) -> valid mixed case.
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    out = particles.compute_particle_spectra(
        str(path), str(tmp_path / "spec"), spectrum_types=["energy"]
    )
    assert out["status"] == "success"
    assert out["spectra"]["energy"]["shape"][0] == 3


def test_inconsistent_field_shape_rejected(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    arrays = _make_dist_arrays(n_time=3)
    arrays["bins"] = np.ones((5, 5))  # wrong (E,A)
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    out = particles.compute_particle_spectra(
        str(path), str(tmp_path / "spec"), spectrum_types=["energy"]
    )
    assert out["status"] == "error"
    assert "bins" in out["message"]


# --------------------------------------------------------------------------
# Opt-in real backend round-trips (skip unless exact functions are importable)
# --------------------------------------------------------------------------

def _have_moments_backend() -> bool:
    try:
        m = importlib.import_module("pyspedas.particles.moments.moments_3d")
        return getattr(m, "moments_3d", None) is not None
    except Exception:
        return False


def _have_spectra_backends() -> bool:
    try:
        for mod, attr in (
            ("pyspedas.particles.spd_part_products.spd_pgs_make_e_spec", "spd_pgs_make_e_spec"),
            ("pyspedas.particles.spd_part_products.spd_pgs_make_phi_spec", "spd_pgs_make_phi_spec"),
            ("pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec", "spd_pgs_make_theta_spec"),
        ):
            if getattr(importlib.import_module(mod), attr, None) is None:
                return False
        return True
    except Exception:
        return False


def _skip_if_backend_incompatible(out: dict) -> None:
    """Skip (not fail) when the real pyspedas build rejects the synthetic schema.

    The round-trips verify *integration* (file-in -> pyspedas algorithm ->
    artifact) on whatever pyspedas build is installed. Algorithm internals vary
    across pyspedas releases: some builds raise on this minimal synthetic
    ``data_in`` (e.g. ``moments_3d`` changed its required keys / units between
    1.7.x and 2.x), which the tool surfaces as a structured ``backend_error``
    rather than crashing. That is the documented contract, not a defect in this
    code, so treat it as a skip with the backend's own message. A real
    regression in the tool would instead surface as a different status/shape and
    still fail loudly below.
    """
    if out.get("status") == "error" and out.get("code") in {
        "backend_error",
        "dependency_missing",
        "unsupported",
    }:
        pytest.skip(f"installed pyspedas rejected the synthetic schema: {out.get('message')}")


@pytest.mark.skipif(not _have_moments_backend(), reason="requires pyspedas moments_3d")
def test_real_moments_roundtrip(tmp_path):
    arrays = _make_dist_arrays()
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    out = particles.compute_particle_moments(
        str(path), str(tmp_path / "mom"), output_format="json"
    )
    _skip_if_backend_incompatible(out)
    assert out["status"] == "success"
    assert out["density_summary"] is not None
    payload = json.loads(Path(out["moments_file"]).read_text())
    assert len(payload["density"]) == arrays["data"].shape[0]
    assert all(np.isfinite(payload["density"]))


@pytest.mark.skipif(not _have_spectra_backends(), reason="requires pyspedas spd_pgs_make_*_spec")
def test_real_spectra_roundtrip(tmp_path):
    arrays = _make_dist_arrays()
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    out = particles.compute_particle_spectra(
        str(path),
        str(tmp_path / "spec"),
        spectrum_types=["energy", "phi", "theta"],
    )
    _skip_if_backend_incompatible(out)
    assert out["status"] == "success"
    assert set(out["succeeded"]) == {"energy", "phi", "theta"}
    espec = np.load(out["spectra"]["energy"]["spectrogram_file"])
    assert espec["spectrogram"].shape[0] == arrays["data"].shape[0]


def _have_fac_backend() -> bool:
    try:
        for mod, attr in (
            ("pyspedas.particles.spd_part_products.spd_pgs_do_fac", "spd_pgs_do_fac"),
            (
                "pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec",
                "spd_pgs_make_theta_spec",
            ),
        ):
            if getattr(importlib.import_module(mod), attr, None) is None:
                return False
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _have_fac_backend(), reason="requires pyspedas spd_pgs_do_fac")
def test_real_pitch_angle_roundtrip(tmp_path):
    # Real FAC pitch-angle pipeline: synthetic distribution + synthetic B field,
    # no network. Asserts a 0-180 deg artifact with finite values is produced.
    arrays = _make_dist_arrays()
    n_time = arrays["data"].shape[0]
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    mag = tmp_path / "mag.npz"
    np.savez(mag, b=np.tile(np.array([0.0, 0.0, 1.0]), (n_time, 1)))
    out = particles.compute_particle_spectra(
        str(path),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
        resolution=18,
    )
    entry = out["spectra"]["pitch_angle"]
    if entry.get("status") in {"unsupported", "error"} and entry.get("code") in {
        "unsupported",
        "backend_error",
    }:
        pytest.skip(f"installed pyspedas FAC backend incompatible: {entry.get('message')}")
    assert out["status"] == "success"
    assert entry["status"] == "success"
    assert entry["shape"] == [n_time, 18]
    lo, hi = entry["axis_range"]
    assert 0.0 <= lo and hi <= 180.0
    spec = np.load(entry["spectrogram_file"])
    assert spec["spectrogram"].shape == (n_time, 18)
    # At least some finite values are produced from the synthetic distribution.
    assert np.isfinite(spec["spectrogram"]).any()


@pytest.mark.skipif(not _have_fac_backend(), reason="requires pyspedas spd_pgs_do_fac")
def test_real_pitch_angle_beam_peaks_along_b(tmp_path):
    # Physics sanity: a beam pointing along +z, with B along +z, must put its
    # peak at low pitch angle (near 0 deg), not high.
    n_energy, n_theta, n_phi = 6, 8, 8
    n_angle = n_theta * n_phi
    theta_vals = np.linspace(-78.75, 78.75, n_theta)
    phi_vals = np.linspace(22.5, 337.5, n_phi)
    th, ph = np.meshgrid(theta_vals, phi_vals, indexing="ij")
    theta = np.repeat(th.reshape(-1)[None, :], n_energy, axis=0)
    phi = np.repeat(ph.reshape(-1)[None, :], n_energy, axis=0)
    dtheta = np.full((n_energy, n_angle), 180.0 / n_theta)
    dphi = np.full((n_energy, n_angle), 360.0 / n_phi)
    bins = np.ones((n_energy, n_angle))
    # Beam concentrated near +z look direction (high latitude theta).
    beam = (th.reshape(-1) > 60.0).astype("float64") + 1e-3
    data = np.repeat(beam[None, :], n_energy, axis=0)[None, ...]
    arrays = {
        "times": np.array([1_600_000_000.0]),
        "data": data,
        "energy": np.repeat(np.geomspace(10.0, 1000.0, n_energy)[:, None], n_angle, axis=1),
        "denergy": np.ones((n_energy, n_angle)),
        "theta": theta,
        "dtheta": dtheta,
        "phi": phi,
        "dphi": dphi,
        "bins": bins,
        "magf": np.array([0.0, 0.0, 5.0]),
        "charge": 1.0,
        "mass": 5.68e-6,
    }
    path = tmp_path / "dist.npz"
    np.savez(path, **arrays)
    mag = tmp_path / "mag.npz"
    np.savez(mag, b=np.array([[0.0, 0.0, 1.0]]))  # B along +z
    out = particles.compute_particle_spectra(
        str(path),
        str(tmp_path / "spec"),
        spectrum_types=["pitch_angle"],
        mag_file=str(mag),
        resolution=9,
    )
    assert out["status"] == "success"
    spec = np.load(out["spectra"]["pitch_angle"]["spectrogram_file"])
    axis = spec["axis"]  # pitch-angle bin centers (deg)
    row = spec["spectrogram"][0]
    finite = np.isfinite(row)
    # Restrict to finite bins; the peak bin should sit in the low-PA half.
    peak_pa = axis[finite][np.nanargmax(row[finite])]
    assert peak_pa < 90.0

# --------------------------------------------------------------------------
# Issue #95: pyspedas converter -> distribution artifact bridge
# --------------------------------------------------------------------------

def _fake_converter_records(n_time: int = 2):
    records = []
    for i in range(n_time):
        data = np.arange(3 * 2 * 2, dtype="float64").reshape(3, 2, 2) + i
        energy = np.repeat(np.array([10.0, 20.0, 40.0])[:, None, None], 2, axis=1)
        energy = np.repeat(energy, 2, axis=2)
        records.append({
            "start_time": 1_700_000_000.0 + i,
            "data": data,
            "energy": energy,
            "denergy": np.ones((3, 2, 2)),
            "theta": np.zeros((3, 2, 2)) + 10.0,
            "dtheta": np.ones((3, 2, 2)) * 5.0,
            "phi": np.zeros((3, 2, 2)) + 20.0,
            "dphi": np.ones((3, 2, 2)) * 5.0,
            "bins": np.ones((3, 2, 2)),
            "charge": 1.0,
            "mass": 1.04535e-2,
        })
    return records


def test_build_particle_distribution_artifact_from_converter(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    mod = types.ModuleType("fake_dist_converter")
    calls = []

    def fake_get_dist(tname, index=None, species=None):
        calls.append({"tname": tname, "index": index, "species": species})
        return _fake_converter_records(2)

    mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_dist_converter", mod)
    monkeypatch.setitem(
        particles._DIST_CONVERTERS,
        "fake",
        ("fake_dist_converter", "fake_get_dist"),
    )

    out_file = tmp_path / "dist_from_cdf.npz"
    out = particles.build_particle_distribution_artifact(
        "mms1_dis_dist_fast",
        str(out_file),
        converter="fake",
        index=[0, 1],
        species="i",
        magf=[0.0, 0.0, 5.0],
    )

    assert out["status"] == "success"
    assert out["output_file"] == str(out_file)
    assert out["shape"] == [2, 3, 4]
    assert out["schema"] == "DIST_SCHEMA_DOC"
    assert calls == [{"tname": "mms1_dis_dist_fast", "index": [0, 1], "species": "i"}]
    with np.load(out_file) as npz:
        assert npz["data"].shape == (2, 3, 4)
        assert npz["magf"].shape == (2, 3)
        assert npz["charge"] == pytest.approx(1.0)
    # The artifact validates through the same normalizer used by moments.
    raw = particles._load_distribution(str(out_file))
    _, cubes, scalars, n_time = particles._normalize_distribution(raw, particles._MOMENTS_REQUIRED)
    assert n_time == 2
    assert cubes["data"].shape == (2, 3, 4)
    assert scalars["mass"] == pytest.approx(1.04535e-2)


def test_build_particle_distribution_requires_magf(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    out = particles.build_particle_distribution_artifact(
        "some_dist",
        str(tmp_path / "dist.npz"),
        converter="mms_fpi",
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "magf" in out["message"]


def test_build_particle_distribution_rejects_unknown_converter(tmp_path):
    out = particles.build_particle_distribution_artifact(
        "some_dist",
        str(tmp_path / "dist.npz"),
        converter="not_a_converter",
        magf=[0, 0, 1],
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "valid_converters" in out


def test_load_particle_distribution_artifact_runs_loader_then_converter(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    loader_mod = types.ModuleType("fake_particle_loader")
    converter_mod = types.ModuleType("fake_loaded_converter")
    calls = {"loader": [], "converter": []}

    def fake_load(trange=None, probe=None, datatype=None, no_update=None):
        calls["loader"].append({
            "trange": trange,
            "probe": probe,
            "datatype": datatype,
            "no_update": no_update,
        })
        return ["mms1_fgm_b_gse_srvy_l2", "mms1_dis_dist_fast"]

    def fake_get_dist(tname, probe=None, data_rate=None, species=None):
        calls["converter"].append({
            "tname": tname,
            "probe": probe,
            "data_rate": data_rate,
            "species": species,
        })
        return _fake_converter_records(2)

    loader_mod.fake_load = fake_load
    converter_mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_particle_loader", loader_mod)
    monkeypatch.setitem(sys.modules, "fake_loaded_converter", converter_mod)
    monkeypatch.setitem(particles._DIST_CONVERTERS, "fake_e2e", ("fake_loaded_converter", "fake_get_dist"))
    monkeypatch.setitem(particles._DIST_LOADERS, "fake_e2e", ("fake_particle_loader", "fake_load", {"datatype": "dist"}))

    out_file = tmp_path / "loaded_dist.npz"
    out = particles.load_particle_distribution_artifact(
        str(out_file),
        converter="fake_e2e",
        trange=["2020-01-01", "2020-01-01/00:01"],
        loader_kwargs={"no_update": True},
        probe="1",
        species="i",
        magf=[0.0, 0.0, 5.0],
    )

    assert out["status"] == "success"
    assert out["tool"] == "load_particle_distribution_artifact"
    assert out["loader_backend"] == "fake_particle_loader.fake_load"
    assert out["loaded_tplot_names"] == ["mms1_fgm_b_gse_srvy_l2", "mms1_dis_dist_fast"]
    assert out["selected_tplot_name"] == "mms1_dis_dist_fast"
    assert calls["loader"] == [{
        "trange": ["2020-01-01", "2020-01-01/00:01"],
        "probe": "1",
        "datatype": "dist",
        "no_update": True,
    }]
    assert calls["converter"] == [{"tname": "mms1_dis_dist_fast", "probe": "1", "data_rate": None, "species": "i"}]
    with np.load(out_file) as npz:
        assert npz["data"].shape == (2, 3, 4)
        assert npz["magf"].shape == (2, 3)


def test_load_particle_distribution_artifact_uses_explicit_tplot_name(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    loader_mod = types.ModuleType("fake_particle_loader_explicit")
    converter_mod = types.ModuleType("fake_loaded_converter_explicit")
    calls = []

    def fake_load(**kwargs):
        return ["not_a_dist_var"]

    def fake_get_dist(tname):
        calls.append(tname)
        return _fake_converter_records(1)

    loader_mod.fake_load = fake_load
    converter_mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_particle_loader_explicit", loader_mod)
    monkeypatch.setitem(sys.modules, "fake_loaded_converter_explicit", converter_mod)
    monkeypatch.setitem(particles._DIST_CONVERTERS, "fake_explicit", ("fake_loaded_converter_explicit", "fake_get_dist"))

    out = particles.load_particle_distribution_artifact(
        str(tmp_path / "explicit_dist.npz"),
        converter="fake_explicit",
        loader_module="fake_particle_loader_explicit",
        loader_function="fake_load",
        tplot_name="explicit_dist_tplot",
        magf=[0.0, 0.0, 1.0],
    )

    assert out["status"] == "success"
    assert out["selected_tplot_name"] == "explicit_dist_tplot"
    assert calls == ["explicit_dist_tplot"]



def test_build_particle_distribution_reads_mag_tplot(tmp_path, monkeypatch):
    base = 1_700_000_000.0

    def fake_get_data(name):
        assert name == "mms1_fgm_b_gse_srvy_l2"
        # Four-column FGM-like payload (Bx, By, Bz, |B|); only first three are used.
        return types.SimpleNamespace(
            times=np.array([base, base + 2.0]),
            y=np.array([[1.0, 2.0, 3.0, 9.0], [3.0, 4.0, 5.0, 12.0]]),
        )

    _install_fake_pyspedas(monkeypatch, get_data=fake_get_data)
    mod = types.ModuleType("fake_dist_converter_mag")

    def fake_get_dist(tname):
        assert tname == "mms1_dis_dist_fast"
        return _fake_converter_records(2)

    mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_dist_converter_mag", mod)
    monkeypatch.setitem(
        particles._DIST_CONVERTERS,
        "fake_mag",
        ("fake_dist_converter_mag", "fake_get_dist"),
    )

    out_file = tmp_path / "dist_from_tplot_b.npz"
    out = particles.build_particle_distribution_artifact(
        "mms1_dis_dist_fast",
        str(out_file),
        converter="fake_mag",
        mag_tplot_name="mms1_fgm_b_gse_srvy_l2",
    )

    assert out["status"] == "success"
    assert out["magf_source"]["mode"] == "tplot"
    assert out["magf_source"]["interpolated"] is True
    with np.load(out_file) as npz:
        assert npz["magf"].shape == (2, 3)
        np.testing.assert_allclose(npz["magf"], [[1.0, 2.0, 3.0], [2.0, 3.0, 4.0]])


def test_load_particle_distribution_artifact_auto_loads_mag_tplot(tmp_path, monkeypatch):
    base = 1_700_000_000.0
    calls = {"loader": [], "mag_loader": [], "converter": []}

    def fake_get_data(name):
        assert name == "mms1_fgm_b_gse_srvy_l2"
        return types.SimpleNamespace(
            times=np.array([base, base + 1.0]),
            y=np.array([[0.0, 0.0, 5.0, 5.0], [0.0, 1.0, 5.0, 5.1]]),
        )

    _install_fake_pyspedas(monkeypatch, get_data=fake_get_data)
    loader_mod = types.ModuleType("fake_particle_loader_auto_mag")
    mag_loader_mod = types.ModuleType("fake_mag_loader_auto_mag")
    converter_mod = types.ModuleType("fake_converter_auto_mag")

    def fake_load(trange=None, probe=None, datatype=None):
        calls["loader"].append({"trange": trange, "probe": probe, "datatype": datatype})
        return ["mms1_dis_dist_fast"]

    def fake_load_mag(trange=None, probe=None, datatype=None, level=None):
        calls["mag_loader"].append({
            "trange": trange,
            "probe": probe,
            "datatype": datatype,
            "level": level,
        })
        return ["mms1_fgm_b_gse_srvy_l2"]

    def fake_get_dist(tname, probe=None):
        calls["converter"].append({"tname": tname, "probe": probe})
        return _fake_converter_records(2)

    loader_mod.fake_load = fake_load
    mag_loader_mod.fake_load_mag = fake_load_mag
    converter_mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_particle_loader_auto_mag", loader_mod)
    monkeypatch.setitem(sys.modules, "fake_mag_loader_auto_mag", mag_loader_mod)
    monkeypatch.setitem(sys.modules, "fake_converter_auto_mag", converter_mod)
    monkeypatch.setitem(particles._DIST_CONVERTERS, "fake_auto_mag", ("fake_converter_auto_mag", "fake_get_dist"))
    monkeypatch.setitem(particles._DIST_LOADERS, "fake_auto_mag", ("fake_particle_loader_auto_mag", "fake_load", {"datatype": "dist"}))
    monkeypatch.setitem(particles._DIST_MAG_LOADERS, "fake_auto_mag", ("fake_mag_loader_auto_mag", "fake_load_mag", {"datatype": "fgm", "level": "l2"}))

    out_file = tmp_path / "loaded_auto_mag.npz"
    out = particles.load_particle_distribution_artifact(
        str(out_file),
        converter="fake_auto_mag",
        trange=["2020-01-01", "2020-01-01/00:01"],
        probe="1",
    )

    assert out["status"] == "success"
    assert out["selected_tplot_name"] == "mms1_dis_dist_fast"
    assert out["selected_mag_tplot_name"] == "mms1_fgm_b_gse_srvy_l2"
    assert out["mag_loader_backend"] == "fake_mag_loader_auto_mag.fake_load_mag"
    assert calls["loader"] == [{"trange": ["2020-01-01", "2020-01-01/00:01"], "probe": "1", "datatype": "dist"}]
    assert calls["mag_loader"] == [{
        "trange": ["2020-01-01", "2020-01-01/00:01"],
        "probe": "1",
        "datatype": "fgm",
        "level": "l2",
    }]
    assert calls["converter"] == [{"tname": "mms1_dis_dist_fast", "probe": "1"}]
    with np.load(out_file) as npz:
        np.testing.assert_allclose(npz["magf"], [[0.0, 0.0, 5.0], [0.0, 1.0, 5.0]])
    sidecar = json.loads(Path(out["metadata_file"]).read_text())
    assert sidecar["tool"] == "load_particle_distribution_artifact"
    assert sidecar["loader_backend"] == "fake_particle_loader_auto_mag.fake_load"
    assert sidecar["mag_loader_backend"] == "fake_mag_loader_auto_mag.fake_load_mag"
    assert sidecar["loaded_tplot_names"] == ["mms1_dis_dist_fast"]
    assert sidecar["loaded_mag_tplot_names"] == ["mms1_fgm_b_gse_srvy_l2"]


def test_build_particle_distribution_rejects_mag_tplot_outside_time_range(tmp_path, monkeypatch):
    base = 1_700_000_000.0

    def fake_get_data(name):
        return types.SimpleNamespace(
            times=np.array([base + 10.0, base + 20.0]),
            y=np.array([[1.0, 0.0, 0.0], [2.0, 0.0, 0.0]]),
        )

    _install_fake_pyspedas(monkeypatch, get_data=fake_get_data)
    mod = types.ModuleType("fake_dist_converter_outside_mag")

    def fake_get_dist(tname):
        return _fake_converter_records(2)

    mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_dist_converter_outside_mag", mod)
    monkeypatch.setitem(
        particles._DIST_CONVERTERS,
        "fake_outside_mag",
        ("fake_dist_converter_outside_mag", "fake_get_dist"),
    )

    out_file = tmp_path / "dist_outside_mag.npz"
    out = particles.build_particle_distribution_artifact(
        "mms1_dis_dist_fast",
        str(out_file),
        converter="fake_outside_mag",
        mag_tplot_name="mms1_fgm_b_gse_srvy_l2",
    )

    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "does not bracket distribution times" in out["message"]
    assert not out_file.exists()


def test_load_particle_distribution_artifact_requires_loader_override_pairs(tmp_path):
    out = particles.load_particle_distribution_artifact(
        str(tmp_path / "partial_loader.npz"),
        converter="mms_fpi",
        loader_module="fake_loader_only",
        magf=[0.0, 0.0, 1.0],
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "loader_module and loader_function" in out["message"]

    out = particles.load_particle_distribution_artifact(
        str(tmp_path / "partial_mag_loader.npz"),
        converter="mms_fpi",
        mag_loader_function="fake_mag_load_only",
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "mag_loader_module and mag_loader_function" in out["message"]


def test_load_particle_distribution_artifact_reports_missing_mag_source(tmp_path, monkeypatch):
    _install_fake_pyspedas(monkeypatch)
    loader_mod = types.ModuleType("fake_particle_loader_no_mag")
    converter_mod = types.ModuleType("fake_converter_no_mag")

    def fake_load(**kwargs):
        return ["mms1_dis_dist_fast"]

    def fake_get_dist(tname):
        return _fake_converter_records(1)

    loader_mod.fake_load = fake_load
    converter_mod.fake_get_dist = fake_get_dist
    monkeypatch.setitem(sys.modules, "fake_particle_loader_no_mag", loader_mod)
    monkeypatch.setitem(sys.modules, "fake_converter_no_mag", converter_mod)
    monkeypatch.setitem(particles._DIST_CONVERTERS, "fake_no_mag", ("fake_converter_no_mag", "fake_get_dist"))
    monkeypatch.setitem(particles._DIST_LOADERS, "fake_no_mag", ("fake_particle_loader_no_mag", "fake_load", {}))
    monkeypatch.delitem(particles._DIST_MAG_LOADERS, "fake_no_mag", raising=False)

    out = particles.load_particle_distribution_artifact(
        str(tmp_path / "missing_mag.npz"),
        converter="fake_no_mag",
    )

    assert out["status"] == "error"
    assert out["code"] == "needs_input"
    assert "magnetic-field" in out["message"]
    assert out["loaded_tplot_names"] == ["mms1_dis_dist_fast"]


# --------------------------------------------------------------------------
# Issue #95: verify the REAL registered converters (signature compatibility)
#
# The converter records themselves require real mission CDFs (network + large
# downloads), which these offline tests deliberately avoid. What is checkable
# offline is the contract the bridge actually relies on: every registered
# (module, attr) imports against the installed pyspedas, and _converter_kwargs
# filters each real signature correctly (drops MMS-only kwargs for ERG, keeps
# units/species/trange). These pin the registry to upstream reality in the
# primary supported environment while still skipping gracefully in builds where
# optional PySPEDAS converters are absent.
# --------------------------------------------------------------------------

_ERG_CONVERTER_KEYS = ("erg_lepi", "erg_lepe", "erg_mepi", "erg_mepe", "erg_hep", "erg_xep")
_MMS_CONVERTER_KEYS = ("mms_fpi", "mms_hpca")


def _converter_importable(key: str) -> bool:
    """True if the registered (module, attr) for ``key`` imports in this build."""
    module_path, attr = particles._DIST_CONVERTERS[key]
    try:
        return getattr(importlib.import_module(module_path), attr, None) is not None
    except Exception:
        return False


@pytest.mark.parametrize("key", sorted(particles._DIST_CONVERTERS))
def test_registered_converter_imports_or_skips(key):
    """Each registered converter resolves to a real callable (skip if absent)."""
    module_path, attr = particles._DIST_CONVERTERS[key]
    if not _converter_importable(key):
        pytest.skip(f"pyspedas build lacks {module_path}.{attr}")
    fn = getattr(importlib.import_module(module_path), attr)
    assert callable(fn)
    # The bridge passes the tplot variable name positionally; every converter
    # must accept a leading positional parameter (tname).
    params = list(inspect.signature(fn).parameters.values())
    assert params, f"{key} converter takes no parameters"
    assert params[0].kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    )


@pytest.mark.parametrize("key", _ERG_CONVERTER_KEYS)
def test_erg_converter_kwargs_drop_mms_only_keep_erg(key):
    """_converter_kwargs drops probe/data_rate for ERG, keeps units/species/trange."""
    if not _converter_importable(key):
        pytest.skip(f"pyspedas build lacks ERG converter {key}")
    module_path, attr = particles._DIST_CONVERTERS[key]
    fn = getattr(importlib.import_module(module_path), attr)
    # Mirror the exact kwargs the bridge assembles (with MMS-only ones populated).
    candidate = {
        "index": [0, 1],
        "probe": "1",        # MMS-only: must be dropped for ERG
        "data_rate": "fast",  # MMS-only: must be dropped for ERG
        "species": "e",
        "level": "l2",
        "units": "flux",
        "trange": ["2017-01-01", "2017-01-02"],
        "single_time": None,  # None values are always dropped
    }
    filtered = particles._converter_kwargs(fn, candidate)
    assert "probe" not in filtered, f"{key} should not accept MMS-only 'probe'"
    assert "data_rate" not in filtered, f"{key} should not accept MMS-only 'data_rate'"
    for keep in ("units", "species", "trange"):
        assert keep in filtered, f"{key} should accept ERG-relevant '{keep}'"
        assert filtered[keep] == candidate[keep]
    assert "single_time" not in filtered  # None is filtered regardless of signature


@pytest.mark.parametrize("key", _MMS_CONVERTER_KEYS)
def test_mms_converter_kwargs_keep_probe_data_rate(key):
    """_converter_kwargs keeps probe/data_rate for the MMS converters that take them."""
    if not _converter_importable(key):
        pytest.skip(f"pyspedas build lacks MMS converter {key}")
    module_path, attr = particles._DIST_CONVERTERS[key]
    fn = getattr(importlib.import_module(module_path), attr)
    candidate = {"probe": "1", "data_rate": "fast", "species": "i", "index": 0}
    filtered = particles._converter_kwargs(fn, candidate)
    assert filtered["probe"] == "1"
    assert filtered["data_rate"] == "fast"
    # ERG-only 'units'/'trange' are not in the MMS signatures and must be dropped.
    sig_params = set(inspect.signature(fn).parameters)
    extra = particles._converter_kwargs(fn, {"units": "flux", "trange": ["a", "b"]})
    assert extra == {}
    assert all(k in sig_params for k in extra)


# --------------------------------------------------------------------------
# Issue #95: ERG-shaped fake converter regression through the full bridge.
#
# Drives build_particle_distribution_artifact with records shaped like a real
# ERG *_get_dist output (3D (E,phi,theta) per-slice grids, ERG-style scalar
# masses/charges, start_time), plus magf synthesis from an injected B tplot
# variable. Exercises the converter path -> _flatten_particle_grid -> magf
# tplot interpolation/provenance sidecar -> schema + moments re-validation,
# all offline (no network, no real CDFs).
# --------------------------------------------------------------------------

def _erg_shaped_records(n_time: int = 3, n_energy: int = 4, n_phi: int = 5, n_theta: int = 2):
    """Records mirroring a real ERG converter's per-slice (E, phi, theta) grids."""
    records = []
    energy_axis = np.geomspace(20.0, 8000.0, n_energy)
    for i in range(n_time):
        grid = (n_energy, n_phi, n_theta)
        # Energy varies along axis 0 only; broadcast across phi/theta like ERG.
        energy = np.broadcast_to(energy_axis[:, None, None], grid).astype("float64")
        phi_axis = np.linspace(0.0, 360.0, n_phi, endpoint=False)
        theta_axis = np.linspace(-78.75, 78.75, n_theta)
        phi = np.broadcast_to(phi_axis[None, :, None], grid).astype("float64")
        theta = np.broadcast_to(theta_axis[None, None, :], grid).astype("float64")
        data = (np.random.RandomState(i).rand(*grid) * 1e5).astype("float64")
        records.append({
            "start_time": 1_500_000_000.0 + 10.0 * i,
            "end_time": 1_500_000_000.0 + 10.0 * i + 8.0,
            "data": data,
            "energy": energy,
            "denergy": energy * 0.25,
            "phi": phi,
            "dphi": np.full(grid, 360.0 / n_phi),
            "theta": theta,
            "dtheta": np.full(grid, 157.5 / n_theta),
            "bins": np.ones(grid),
            "charge": -1.0,          # ERG LEP-e electron product
            "mass": 5.68566e-06,     # electron mass, pyspedas eV/(km/s)^2 units
        })
    return records


def test_build_artifact_from_erg_shaped_converter_with_mag_tplot(tmp_path, monkeypatch):
    """ERG-shaped 3D records flatten + magf synth + schema/moments validation."""
    n_time = 3
    records = _erg_shaped_records(n_time=n_time)
    # B tplot variable bracketing the distribution slices so interpolation
    # (not broadcast) drives the magf-provenance path.
    dist_times = np.array([r["start_time"] for r in records], dtype="float64")
    b_times = np.array([dist_times[0] - 5.0, dist_times[-1] + 5.0], dtype="float64")
    b_vals = np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 9.0]], dtype="float64")

    def fake_get_data(name):
        if name == "erg_mgf_8sec":
            return {"times": b_times, "y": b_vals}
        return None

    _install_fake_pyspedas(monkeypatch, get_data=fake_get_data)
    mod = types.ModuleType("fake_erg_converter")
    calls = []

    def erg_lepe_get_dist(tname, index=None, units="flux", level="l2", species="e",
                          time_only=False, single_time=None, trange=None):
        calls.append({"tname": tname, "units": units, "species": species, "trange": trange})
        return records

    mod.erg_lepe_get_dist = erg_lepe_get_dist
    monkeypatch.setitem(sys.modules, "fake_erg_converter", mod)
    monkeypatch.setitem(
        particles._DIST_CONVERTERS,
        "erg_shaped",
        ("fake_erg_converter", "erg_lepe_get_dist"),
    )

    out_file = tmp_path / "erg_dist.npz"
    out = particles.build_particle_distribution_artifact(
        "erg_lepe_l2_3dflux_FEDU",
        str(out_file),
        converter="erg_shaped",
        units="flux",
        species="e",
        trange=["2017-07-14", "2017-07-15"],
        # MMS-only kwargs: the bridge must drop these for the ERG signature.
        probe="1",
        data_rate="fast",
        mag_tplot_name="erg_mgf_8sec",
    )

    assert out["status"] == "success", out
    # 3D (E, phi, theta) -> flattened (E, phi*theta) angular axis.
    assert out["shape"] == [n_time, 4, 10]
    assert out["converter"] == "erg_shaped"
    assert out["magf_source"]["mode"] == "tplot"
    assert out["magf_source"]["tplot_name"] == "erg_mgf_8sec"
    assert out["magf_source"]["interpolated"] is True
    # ERG signature accepted units/species/trange and dropped probe/data_rate.
    assert calls == [{
        "tname": "erg_lepe_l2_3dflux_FEDU",
        "units": "flux",
        "species": "e",
        "trange": ["2017-07-14", "2017-07-15"],
    }]
    assert "probe" not in out["converter_kwargs"]
    assert "data_rate" not in out["converter_kwargs"]

    # Sidecar provenance written and self-consistent.
    sidecar = json.loads(Path(out["metadata_file"]).read_text())
    assert sidecar["converter"] == "erg_shaped"
    assert sidecar["magf_source"]["tplot_name"] == "erg_mgf_8sec"

    # The written artifact round-trips through the moments normalizer.
    with np.load(out_file) as npz:
        assert npz["data"].shape == (n_time, 4, 10)
        assert npz["magf"].shape == (n_time, 3)
        assert npz["charge"] == pytest.approx(-1.0)
    raw = particles._load_distribution(str(out_file))
    times, cubes, scalars, nt = particles._normalize_distribution(raw, particles._MOMENTS_REQUIRED)
    assert nt == n_time
    assert cubes["data"].shape == (n_time, 4, 10)
    assert scalars["mass"] == pytest.approx(5.68566e-06)
    # magf was interpolated between the two bracketing B samples: Bz rises 3->9.
    assert cubes["magf"][0, 2] < cubes["magf"][-1, 2]


def test_build_artifact_converter_missing_field_names_converter_and_field(tmp_path, monkeypatch):
    """A converter record lacking a field raises an error naming key + field."""
    _install_fake_pyspedas(monkeypatch)
    mod = types.ModuleType("fake_partial_converter")

    def partial_get_dist(tname):
        recs = _erg_shaped_records(n_time=1)
        del recs[0]["denergy"]  # drop a required field
        return recs

    mod.partial_get_dist = partial_get_dist
    monkeypatch.setitem(sys.modules, "fake_partial_converter", mod)
    monkeypatch.setitem(
        particles._DIST_CONVERTERS,
        "erg_partial",
        ("fake_partial_converter", "partial_get_dist"),
    )

    out = particles.build_particle_distribution_artifact(
        "erg_partial_tplot",
        str(tmp_path / "partial.npz"),
        converter="erg_partial",
        magf=[0.0, 0.0, 5.0],
    )
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"
    assert "erg_partial" in out["message"]      # names the converter key
    assert "denergy" in out["message"]          # names the missing field
    assert "fake_partial_converter.partial_get_dist" in out["message"]
