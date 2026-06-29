"""Offline tests for the FDSN/MTH5 data-source adapter (issue #22).

These tests run without network access and without ``mth5``/``obspy``/``pyspedas``
installed:

- Argument validation happens before any backend import and is checked directly.
- The "optional [fdsn] extra missing" guard is verified by forcing the import to
  fail.
- The browse/fetch artifact-first logic (station flattening, calibrated series
  written to a file, channel/units metadata) is exercised against a lightweight
  fake ``pyspedas`` / ``pyspedas.mth5`` injected into ``sys.modules``.
"""
from __future__ import annotations

import builtins
import csv
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from spedas_agent_kit.datasources import fdsn


# --------------------------------------------------------------------------
# Fake pyspedas.mth5 backend
# --------------------------------------------------------------------------

def _install_fake_pyspedas(monkeypatch, *, datasets_result=None, load_var="fdsn_4P_ALW48",
                           series=None, metadata=None, load_raises=None):
    """Inject a fake ``pyspedas`` + ``pyspedas.mth5`` tree into sys.modules.

    - ``pyspedas.mth5.utilities.datasets(...)`` -> ``datasets_result``
    - ``pyspedas.mth5.load_fdsn(...)`` -> ``load_var`` (or raises ``load_raises``)
    - ``pyspedas.get_data(name)`` -> ``series`` namespace; ``metadata=True`` ->
      ``metadata`` dict
    """
    pyspedas = types.ModuleType("pyspedas")
    mth5_module = types.ModuleType("pyspedas.mth5")
    utilities = types.ModuleType("pyspedas.mth5.utilities")

    def datasets(trange=None, network=None, station=None, USAarea=False):
        return datasets_result

    def load_fdsn(trange=None, network=None, station=None):
        if load_raises is not None:
            raise load_raises
        return load_var

    def get_data(name, metadata=False):
        if metadata:
            return metadata if False else _METADATA_HOLDER.get("meta")
        return _SERIES_HOLDER.get("series")

    # Stash so the closures above can be overridden per-test without rebuilding.
    _SERIES_HOLDER["series"] = series
    _METADATA_HOLDER["meta"] = metadata

    utilities.datasets = datasets
    mth5_module.utilities = utilities
    mth5_module.load_fdsn = load_fdsn
    pyspedas.mth5 = mth5_module
    pyspedas.get_data = get_data

    monkeypatch.setitem(sys.modules, "pyspedas", pyspedas)
    monkeypatch.setitem(sys.modules, "pyspedas.mth5", mth5_module)
    monkeypatch.setitem(sys.modules, "pyspedas.mth5.utilities", utilities)
    return pyspedas


_SERIES_HOLDER: dict = {}
_METADATA_HOLDER: dict = {}


SAMPLE_DATASETS = {
    "4P": {
        "ALW48": {
            ("2015-06-18T15:00:36.0000", "2015-07-09T13:45:10.0000"): ["LFE", "LFN", "LFZ"],
        }
    }
}


def _series():
    return types.SimpleNamespace(
        times=np.array([1.0, 2.0, 3.0]),
        y=np.array([[10.0, 20.0, 30.0], [11.0, 21.0, 31.0], [12.0, 22.0, 32.0]]),
    )


# --------------------------------------------------------------------------
# browse_fdsn_datasets
# --------------------------------------------------------------------------

def test_browse_lists_stations(monkeypatch):
    _install_fake_pyspedas(monkeypatch, datasets_result=SAMPLE_DATASETS)
    out = fdsn.browse_fdsn_datasets(["2015-06-22", "2015-06-23"], network="4P", station="ALW48")
    assert out["status"] == "success"
    assert out["station_count"] == 1
    st = out["stations"][0]
    assert st["network"] == "4P"
    assert st["station"] == "ALW48"
    assert st["channels"] == ["LFE", "LFN", "LFZ"]
    assert st["time_range"]["start"].startswith("2015-06-18")


def test_browse_empty_result(monkeypatch):
    _install_fake_pyspedas(monkeypatch, datasets_result={})
    out = fdsn.browse_fdsn_datasets(["2015-06-22", "2015-06-23"])
    assert out["status"] == "success"
    assert out["station_count"] == 0
    assert out["stations"] == []


def test_browse_none_result(monkeypatch):
    _install_fake_pyspedas(monkeypatch, datasets_result=None)
    out = fdsn.browse_fdsn_datasets(["2015-06-22", "2015-06-23"])
    assert out["status"] == "success"
    assert out["station_count"] == 0


@pytest.mark.parametrize("trange", [["2015-06-22"], "2015-06-22", [], ["", "2015-06-23"]])
def test_browse_bad_trange(trange):
    out = fdsn.browse_fdsn_datasets(trange)
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"


def test_browse_missing_dependency(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyspedas.mth5" or name.startswith("pyspedas.mth5"):
            raise ImportError("MTH5 must be installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas.mth5", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = fdsn.browse_fdsn_datasets(["2015-06-22", "2015-06-23"])
    assert out["code"] == "missing_dependency"
    assert out["extra"] == "fdsn"
    assert "spedas-agent-kit[fdsn]" in out["hint"]
    assert "Original import failed with ImportError" in out["message"]
    assert "import error:" not in out["message"]


# --------------------------------------------------------------------------
# fetch_fdsn_data
# --------------------------------------------------------------------------

def test_fetch_writes_csv(monkeypatch, tmp_path: Path):
    _install_fake_pyspedas(
        monkeypatch,
        series=_series(),
        metadata={"legend_names": ["hx", "hy", "hz"], "ysubtitle": "[nT]"},
    )
    out = fdsn.fetch_fdsn_data(
        trange=["2015-06-22", "2015-06-23"],
        network="4P", station="ALW48",
        output_dir=str(tmp_path), format="csv",
    )
    assert out["status"] == "success"
    assert out["rows"] == 3
    assert out["channels"] == ["hx", "hy", "hz"]
    assert out["units"] == "[nT]"
    file_path = Path(out["file_path"])
    assert file_path.exists()
    with file_path.open() as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    assert header == ["time", "hx", "hy", "hz"]
    assert rows[0] == ["1.0", "10.0", "20.0", "30.0"]


def test_fetch_writes_json_and_default_channels(monkeypatch, tmp_path: Path):
    _install_fake_pyspedas(monkeypatch, series=_series(), metadata={})
    out = fdsn.fetch_fdsn_data(
        trange=["2015-06-22", "2015-06-23"],
        network="4P", station="ALW48",
        output_dir=str(tmp_path), format="json",
    )
    assert out["status"] == "success"
    # No legend_names -> default Hx/Hy/Hz.
    assert out["channels"] == ["hx", "hy", "hz"]
    payload = json.loads(Path(out["file_path"]).read_text())
    assert payload["time"] == [1.0, 2.0, 3.0]
    assert payload["hx"] == [10.0, 11.0, 12.0]


def test_fetch_no_data_returns_resource_not_found(monkeypatch, tmp_path: Path):
    _install_fake_pyspedas(monkeypatch, load_var=None)
    out = fdsn.fetch_fdsn_data(
        trange=["2015-06-22", "2015-06-23"],
        network="4P", station="ALW48",
        output_dir=str(tmp_path),
    )
    assert out["status"] == "error"
    assert out["code"] == "resource_not_found"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(trange=["a"], network="4P", station="ALW48"),
        dict(trange=["2015-06-22", "2015-06-23"], network="", station="ALW48"),
        dict(trange=["2015-06-22", "2015-06-23"], network="4P", station=""),
    ],
)
def test_fetch_validation_errors(tmp_path: Path, kwargs):
    out = fdsn.fetch_fdsn_data(output_dir=str(tmp_path), **kwargs)
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"


def test_fetch_bad_format(tmp_path: Path):
    out = fdsn.fetch_fdsn_data(
        trange=["2015-06-22", "2015-06-23"], network="4P", station="ALW48",
        output_dir=str(tmp_path), format="parquet",
    )
    assert out["code"] == "invalid_argument"


def test_fetch_missing_dependency(monkeypatch, tmp_path: Path):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("pyspedas.mth5"):
            raise ImportError("MTH5 must be installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "pyspedas.mth5", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = fdsn.fetch_fdsn_data(
        trange=["2015-06-22", "2015-06-23"], network="4P", station="ALW48",
        output_dir=str(tmp_path),
    )
    assert out["code"] == "missing_dependency"
    assert out["extra"] == "fdsn"
