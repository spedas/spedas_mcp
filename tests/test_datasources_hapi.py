"""Offline tests for the HAPI data-source adapter (issue #21).

These tests run without network access and without ``hapiclient`` installed:

- Argument validation happens before any backend import and is checked directly.
- The "optional [hapi] extra missing" guard is verified by forcing the import to
  fail.
- The browse/fetch artifact-first logic (file writing, parameter metadata,
  vector flattening) is exercised against a lightweight fake ``hapiclient``
  injected into ``sys.modules``.
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

from spedas_mcp.datasources import hapi


# --------------------------------------------------------------------------
# Fake hapiclient backend
# --------------------------------------------------------------------------

def _install_fake_hapiclient(monkeypatch, *, catalog=None, data=None, meta=None):
    """Inject a fake ``hapiclient`` module whose ``hapi`` dispatches like the real one.

    ``hapi(server)`` -> catalog dict; ``hapi(server, dataset, params, start, stop)``
    -> ``(data, meta)``.
    """
    module = types.ModuleType("hapiclient")

    def fake_hapi(*args, **kwargs):
        if len(args) == 1:
            return catalog
        return data, meta

    module.hapi = fake_hapi
    monkeypatch.setitem(sys.modules, "hapiclient", module)
    return module


SAMPLE_CATALOG = {
    "catalog": [
        {"id": "OMNI_HRO2_1MIN", "title": "OMNI 1-min merged solar wind"},
        {"id": "AC_H0_MFI", "title": "ACE magnetic field 16-sec"},
        {"id": "NO_TITLE_DS"},
    ]
}


def _structured_data():
    """A structured array with a time field, a scalar field, and a 3-vector field."""
    dt = np.dtype([("Time", "S24"), ("BZ_GSE", "<f8"), ("V_GSE", "<f8", (3,))])
    arr = np.zeros(3, dtype=dt)
    arr["Time"] = [b"2003-10-20T00:00:00Z", b"2003-10-20T00:01:00Z", b"2003-10-20T00:02:00Z"]
    arr["BZ_GSE"] = [1.0, 2.0, 3.0]
    arr["V_GSE"] = [[400.0, 1.0, 2.0], [401.0, 1.5, 2.5], [402.0, 2.0, 3.0]]
    return arr


SAMPLE_META = {
    "parameters": [
        {"name": "Time", "type": "isotime"},
        {"name": "BZ_GSE", "units": "nT", "description": "Bz GSE", "type": "double"},
        {"name": "V_GSE", "units": "km/s", "description": "Velocity GSE", "type": "double", "size": [3]},
    ]
}


# --------------------------------------------------------------------------
# browse_hapi_catalog
# --------------------------------------------------------------------------

def test_browse_lists_datasets(monkeypatch):
    _install_fake_hapiclient(monkeypatch, catalog=SAMPLE_CATALOG)
    out = hapi.browse_hapi_catalog("https://cdaweb.gsfc.nasa.gov/hapi")
    assert out["status"] == "success"
    assert out["server"] == "https://cdaweb.gsfc.nasa.gov/hapi"
    assert out["dataset_count"] == 3
    ids = {d["id"] for d in out["datasets"]}
    assert {"OMNI_HRO2_1MIN", "AC_H0_MFI", "NO_TITLE_DS"} == ids
    assert out["title_count"] == 2
    # Entry without a title omits the misleading null title key.
    no_title = next(d for d in out["datasets"] if d["id"] == "NO_TITLE_DS")
    assert "title" not in no_title


def test_browse_all_missing_titles_omits_nulls_and_adds_note(monkeypatch):
    _install_fake_hapiclient(monkeypatch, catalog={"catalog": [{"id": "DS1"}, {"id": "DS2"}]})
    out = hapi.browse_hapi_catalog("https://cdaweb.gsfc.nasa.gov/hapi")
    assert out["status"] == "success"
    assert out["dataset_count"] == 2
    assert out["title_count"] == 0
    assert all("title" not in d for d in out["datasets"])
    assert "did not include dataset titles" in out["note"]


def test_browse_query_filters(monkeypatch):
    _install_fake_hapiclient(monkeypatch, catalog=SAMPLE_CATALOG)
    out = hapi.browse_hapi_catalog("https://x/hapi", query="omni")
    assert out["dataset_count"] == 1
    assert out["datasets"][0]["id"] == "OMNI_HRO2_1MIN"
    # Title-substring match also works (case-insensitive).
    out2 = hapi.browse_hapi_catalog("https://x/hapi", query="magnetic field")
    assert {d["id"] for d in out2["datasets"]} == {"AC_H0_MFI"}


def test_browse_requires_server():
    out = hapi.browse_hapi_catalog("   ")
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"


def test_browse_missing_dependency(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "hapiclient":
            raise ImportError("No module named 'hapiclient'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "hapiclient", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = hapi.browse_hapi_catalog("https://x/hapi")
    assert out["status"] == "error"
    assert out["code"] == "missing_dependency"
    assert out["extra"] == "hapi"
    assert "spedas-mcp[hapi]" in out["hint"]


# --------------------------------------------------------------------------
# fetch_hapi_data
# --------------------------------------------------------------------------

def test_fetch_writes_csv_and_metadata(monkeypatch, tmp_path: Path):
    _install_fake_hapiclient(monkeypatch, data=_structured_data(), meta=SAMPLE_META)
    out = hapi.fetch_hapi_data(
        server_url="https://x/hapi",
        dataset_id="OMNI_HRO2_1MIN",
        parameters=["BZ_GSE", "V_GSE"],
        start="2003-10-20T00:00:00",
        stop="2003-10-20T00:03:00",
        output_dir=str(tmp_path),
        format="csv",
    )
    assert out["status"] == "success"
    assert out["rows"] == 3
    file_path = Path(out["file_path"])
    assert file_path.exists()
    assert file_path.suffix == ".csv"

    # Parameter metadata is compact and present for both params.
    meta = out["parameters_meta"]
    assert meta["BZ_GSE"]["units"] == "nT"
    assert meta["BZ_GSE"]["rows"] == 3
    assert meta["V_GSE"]["units"] == "km/s"

    # Vector parameter flattened to V_GSE[0..2]; time column decoded from bytes.
    with file_path.open() as fh:
        reader = csv.reader(fh)
        header = next(reader)
        rows = list(reader)
    assert header == ["time", "BZ_GSE", "V_GSE[0]", "V_GSE[1]", "V_GSE[2]"]
    assert rows[0][0] == "2003-10-20T00:00:00Z"
    assert rows[0][2] == "400.0"
    assert len(rows) == 3


def test_fetch_writes_json(monkeypatch, tmp_path: Path):
    _install_fake_hapiclient(monkeypatch, data=_structured_data(), meta=SAMPLE_META)
    out = hapi.fetch_hapi_data(
        server_url="https://x/hapi",
        dataset_id="OMNI_HRO2_1MIN",
        parameters=["BZ_GSE"],
        start="2003-10-20",
        stop="2003-10-21",
        output_dir=str(tmp_path),
        format="json",
    )
    assert out["status"] == "success"
    payload = json.loads(Path(out["file_path"]).read_text())
    assert payload["time"][0] == "2003-10-20T00:00:00Z"
    assert payload["BZ_GSE"] == [1.0, 2.0, 3.0]


def test_fetch_does_not_overwrite(monkeypatch, tmp_path: Path):
    _install_fake_hapiclient(monkeypatch, data=_structured_data(), meta=SAMPLE_META)
    kwargs = dict(
        server_url="https://x/hapi",
        dataset_id="DS",
        parameters=["BZ_GSE"],
        start="2003-10-20",
        stop="2003-10-21",
        output_dir=str(tmp_path),
        format="csv",
    )
    first = hapi.fetch_hapi_data(**kwargs)
    second = hapi.fetch_hapi_data(**kwargs)
    assert first["file_path"] != second["file_path"]
    assert Path(first["file_path"]).exists()
    assert Path(second["file_path"]).exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(server_url="", dataset_id="d", parameters=["p"], start="a", stop="b"),
        dict(server_url="s", dataset_id="", parameters=["p"], start="a", stop="b"),
        dict(server_url="s", dataset_id="d", parameters=[], start="a", stop="b"),
        dict(server_url="s", dataset_id="d", parameters=["p"], start="", stop="b"),
    ],
)
def test_fetch_validation_errors(tmp_path: Path, kwargs):
    out = hapi.fetch_hapi_data(output_dir=str(tmp_path), **kwargs)
    assert out["status"] == "error"
    assert out["code"] == "invalid_argument"


def test_fetch_bad_format(tmp_path: Path):
    out = hapi.fetch_hapi_data(
        server_url="s", dataset_id="d", parameters=["p"], start="a", stop="b",
        output_dir=str(tmp_path), format="parquet",
    )
    assert out["code"] == "invalid_argument"


def test_fetch_missing_dependency(monkeypatch, tmp_path: Path):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "hapiclient":
            raise ImportError("No module named 'hapiclient'")
        return real_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "hapiclient", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = hapi.fetch_hapi_data(
        server_url="https://x/hapi", dataset_id="d", parameters=["p"],
        start="a", stop="b", output_dir=str(tmp_path),
    )
    assert out["code"] == "missing_dependency"
    assert out["extra"] == "hapi"


def test_fetch_non_structured_payload(monkeypatch, tmp_path: Path):
    _install_fake_hapiclient(monkeypatch, data=np.zeros(3), meta=SAMPLE_META)
    out = hapi.fetch_hapi_data(
        server_url="https://x/hapi", dataset_id="d", parameters=["p"],
        start="a", stop="b", output_dir=str(tmp_path),
    )
    assert out["status"] == "error"
    assert out["code"] == "backend_error"
