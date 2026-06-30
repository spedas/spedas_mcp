"""Dependency-free validation for paper-reproduction provenance records.

The Agent Kit ships a canonical, machine-readable provenance schema next to the
``paper-reproduction`` skill (see
``resources/schemas/reproduction_provenance.schema.json``). This module loads
that schema and validates a candidate ``provenance.json`` object against it.

The validation is deliberately **dependency-free** (no ``jsonschema`` /
``pydantic``), matching the project's hand-rolled, dependency-light idiom
(``skill_catalog._parse_frontmatter``, ``server._validate_fetch_time_range``).
It checks *shape* only — required top-level keys, allowed status/quality labels,
and ``trange_utc`` parseability/order. It does **not** assert that a reproduction is
scientifically correct or paper-quality; callers must not read a ``valid: true``
result as an endorsement of reproduction quality.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib import resources
from typing import Any

_SCHEMA_PACKAGE = "spedas_agent_kit.resources.schemas"
_SCHEMA_FILE = "reproduction_provenance.schema.json"

# Required top-level keys for a provenance record. Kept in sync with the schema's
# top-level ``required`` array; the test-suite asserts they match so the two
# cannot silently drift.
REQUIRED_TOP_LEVEL_KEYS: tuple[str, ...] = (
    "paper",
    "target",
    "event_assumption",
    "data_plan",
    "environment",
    "status",
)

# Allowed values for ``target.status_label`` (the per-attempt quality label
# documented in paper-reproduction/SKILL.md "Quality labels").
ALLOWED_STATUS_LABELS: tuple[str, ...] = (
    "paper_quality",
    "proxy",
    "candidate_interval",
    "partial_success",
)

# Allowed values for the overall run ``status`` field.
ALLOWED_RUN_STATUS: tuple[str, ...] = (
    "success",
    "partial-success",
    "failed",
)


def load_provenance_schema() -> dict[str, Any]:
    """Load and parse the canonical reproduction-provenance JSON schema.

    Returns the schema document as a plain dict. Raises ``json.JSONDecodeError``
    if the packaged schema is malformed (it never should be; a test guards it).
    """
    text = (
        resources.files(_SCHEMA_PACKAGE)
        .joinpath(_SCHEMA_FILE)
        .read_text(encoding="utf-8")
    )
    return json.loads(text)


def _parse_utc_timestamp(value: str) -> datetime | None:
    """Parse the timestamp styles used by SPEDAS provenance records.

    Paper-reproduction provenance examples and event presets use the
    ``YYYY-MM-DD/hh:mm:ss`` form that PySPEDAS users recognize. The parser also
    accepts common ISO-8601 UTC strings (``...T...Z`` / ``...+00:00``) so callers
    do not have to rewrite already-valid UTC provenance. Returns ``None`` when
    the value is not parseable as an aware or UTC-assumed timestamp.
    """
    candidate = value.strip()
    for fmt in ("%Y-%m-%d/%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(candidate, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        normalized = candidate.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_trange(value: Any) -> bool:
    """True when ``value`` is a 2-element, parseable, increasing UTC range."""
    if not isinstance(value, list) or len(value) != 2:
        return False
    if not all(isinstance(item, str) and item.strip() for item in value):
        return False
    start = _parse_utc_timestamp(value[0])
    stop = _parse_utc_timestamp(value[1])
    return start is not None and stop is not None and stop > start


def validate_reproduction_provenance(obj: Any) -> dict[str, Any]:
    """Validate the *shape* of a reproduction provenance record.

    Returns a structured dict::

        {"valid": bool, "errors": [{"field": str, "code": str, "message": str}, ...]}

    The check is intentionally shape-only and dependency-free. A ``valid: True``
    result asserts the record carries the required keys, an allowed status label,
    an allowed run status, and a parseable increasing ``event_assumption.trange_utc``. It
    does **not** assert the reproduction is scientifically correct or
    paper-quality.
    """
    errors: list[dict[str, str]] = []

    if not isinstance(obj, dict):
        errors.append(
            {
                "field": "<root>",
                "code": "not_an_object",
                "message": "provenance record must be a JSON object",
            }
        )
        return {"valid": False, "errors": errors}

    # Required top-level keys.
    for key in REQUIRED_TOP_LEVEL_KEYS:
        if key not in obj:
            errors.append(
                {
                    "field": key,
                    "code": "missing_required_key",
                    "message": f"missing required top-level key: {key}",
                }
            )

    # target.status_label
    target = obj.get("target")
    if isinstance(target, dict):
        label = target.get("status_label")
        if label is None:
            errors.append(
                {
                    "field": "target.status_label",
                    "code": "missing_required_key",
                    "message": "target.status_label is required",
                }
            )
        elif label not in ALLOWED_STATUS_LABELS:
            errors.append(
                {
                    "field": "target.status_label",
                    "code": "unknown_status_label",
                    "message": (
                        f"unknown status_label {label!r}; "
                        f"allowed: {', '.join(ALLOWED_STATUS_LABELS)}"
                    ),
                }
            )
    elif "target" in obj:
        errors.append(
            {
                "field": "target",
                "code": "wrong_type",
                "message": "target must be an object",
            }
        )

    # event_assumption.trange_utc
    event = obj.get("event_assumption")
    if isinstance(event, dict):
        trange = event.get("trange_utc")
        if trange is None:
            errors.append(
                {
                    "field": "event_assumption.trange_utc",
                    "code": "missing_required_key",
                    "message": "event_assumption.trange_utc is required",
                }
            )
        elif not _is_trange(trange):
            errors.append(
                {
                    "field": "event_assumption.trange_utc",
                    "code": "malformed_trange",
                    "message": (
                        "event_assumption.trange_utc must be a 2-element list of "
                        "parseable, increasing [start, stop] UTC strings"
                    ),
                }
            )
    elif "event_assumption" in obj:
        errors.append(
            {
                "field": "event_assumption",
                "code": "wrong_type",
                "message": "event_assumption must be an object",
            }
        )

    # status (overall run status)
    status = obj.get("status")
    if status is not None and status not in ALLOWED_RUN_STATUS:
        errors.append(
            {
                "field": "status",
                "code": "unknown_run_status",
                "message": (
                    f"unknown status {status!r}; "
                    f"allowed: {', '.join(ALLOWED_RUN_STATUS)}"
                ),
            }
        )

    return {"valid": not errors, "errors": errors}
