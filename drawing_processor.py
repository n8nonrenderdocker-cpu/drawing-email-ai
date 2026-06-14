from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional

import ezdxf

from config import Settings
from models import FingerprintResult


LOGGER = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {".dxf", ".dwg"}


def is_supported_drawing(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_EXTENSIONS


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint_attachment(settings: Settings, filename: str, data: bytes) -> FingerprintResult:
    file_hash = sha256_bytes(data)
    suffix = Path(filename).suffix.lower()
    warnings: list[str] = []
    drawing_code = detect_drawing_code(filename, data)

    with tempfile.TemporaryDirectory() as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        source_path = temp_dir / safe_temp_filename(filename)
        source_path.write_bytes(data)

        parse_path = source_path
        if suffix == ".dwg":
            converted = convert_dwg_to_dxf(settings, source_path, temp_dir)
            if not converted:
                warnings.append(
                    "DWG file received but no converter produced a DXF. Exact hash was checked; "
                    "geometry comparison needs manual review or a configured converter."
                )
                return FingerprintResult(
                    file_hash=file_hash,
                    geometry_fingerprint=None,
                    geometry_summary={},
                    drawing_code=drawing_code,
                    confidence="low",
                    warnings=warnings,
                )
            parse_path = converted

        try:
            doc = ezdxf.readfile(parse_path)
            summary, canonical_entities = summarize_dxf(doc, settings.geometry_round_precision)
        except Exception as exc:
            LOGGER.exception("Could not parse drawing %s", filename)
            warnings.append(f"Drawing parser failed: {exc}")
            return FingerprintResult(
                file_hash=file_hash,
                geometry_fingerprint=None,
                geometry_summary={},
                drawing_code=drawing_code,
                confidence="low",
                warnings=warnings,
            )

    canonical_json = json.dumps(canonical_entities, sort_keys=True, separators=(",", ":"))
    geometry_fingerprint = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    unsupported_total = sum(summary.get("unsupported_entity_counts", {}).values())
    supported_total = summary.get("supported_entity_total", 0)
    total = supported_total + unsupported_total
    unsupported_ratio = unsupported_total / total if total else 1.0
    confidence = "high"
    if supported_total == 0 or unsupported_ratio > settings.low_confidence_max_unsupported_ratio:
        confidence = "low"
        warnings.append(
            f"Low fingerprint confidence: supported={supported_total}, unsupported={unsupported_total}."
        )
    elif unsupported_total:
        confidence = "medium"
        warnings.append(
            f"Some entities were summarized only by type: supported={supported_total}, unsupported={unsupported_total}."
        )

    return FingerprintResult(
        file_hash=file_hash,
        geometry_fingerprint=geometry_fingerprint,
        geometry_summary=summary,
        drawing_code=drawing_code,
        confidence=confidence,
        warnings=warnings,
    )


def convert_dwg_to_dxf(settings: Settings, source_path: Path, work_dir: Path) -> Optional[Path]:
    if not settings.dwg_converter_command:
        return None

    output_dir = work_dir / "converted"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = settings.dwg_converter_command.format(
        input=str(source_path),
        input_dir=str(source_path.parent),
        output_dir=str(output_dir),
    )
    try:
        subprocess.run(command, shell=True, check=True, capture_output=True, text=True, timeout=120)
    except subprocess.SubprocessError as exc:
        LOGGER.warning("DWG converter failed for %s: %s", source_path, exc)
        return None

    dxf_candidates = list(output_dir.rglob("*.dxf"))
    if not dxf_candidates:
        LOGGER.warning("DWG converter completed but produced no DXF for %s", source_path)
        return None

    expected = output_dir / f"{source_path.stem}.dxf"
    if expected.exists():
        return expected
    return dxf_candidates[0]


def summarize_dxf(doc: ezdxf.EzDxf, precision: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    canonical_entities: list[dict[str, Any]] = []
    unsupported = Counter()
    entity_counts = Counter()
    layers = set()
    blocks = set()
    text_labels = []
    points: list[tuple[float, float, float]] = []

    for entity in doc.modelspace():
        dxftype = entity.dxftype()
        entity_counts[dxftype] += 1
        layer = getattr(entity.dxf, "layer", "0")
        layers.add(layer)

        canonical = canonicalize_entity(entity, precision)
        if canonical is None:
            unsupported[dxftype] += 1
            canonical_entities.append({"type": dxftype, "layer": layer})
            continue

        canonical_entities.append(canonical)
        points.extend(extract_points(canonical))
        if dxftype == "INSERT" and "block" in canonical:
            blocks.add(canonical["block"])
        if dxftype in {"TEXT", "MTEXT"} and canonical.get("text"):
            text_labels.append(canonical["text"])

    canonical_entities.sort(key=lambda item: json.dumps(item, sort_keys=True))
    bbox = bounding_box(points, precision)
    summary = {
        "entity_counts": dict(sorted(entity_counts.items())),
        "supported_entity_total": len(canonical_entities) - sum(unsupported.values()),
        "unsupported_entity_counts": dict(sorted(unsupported.items())),
        "layer_names": sorted(layers),
        "block_names": sorted(blocks),
        "text_labels": sorted(set(text_labels))[:100],
        "bounding_box": bbox,
    }
    return summary, canonical_entities


def canonicalize_entity(entity, precision: int) -> Optional[dict[str, Any]]:
    dxftype = entity.dxftype()
    layer = getattr(entity.dxf, "layer", "0")
    base = {"type": dxftype, "layer": layer}

    if dxftype == "LINE":
        return {
            **base,
            "start": point(entity.dxf.start, precision),
            "end": point(entity.dxf.end, precision),
        }
    if dxftype == "CIRCLE":
        return {
            **base,
            "center": point(entity.dxf.center, precision),
            "radius": number(entity.dxf.radius, precision),
        }
    if dxftype == "ARC":
        return {
            **base,
            "center": point(entity.dxf.center, precision),
            "radius": number(entity.dxf.radius, precision),
            "start_angle": number(entity.dxf.start_angle, precision),
            "end_angle": number(entity.dxf.end_angle, precision),
        }
    if dxftype == "LWPOLYLINE":
        return {
            **base,
            "closed": bool(entity.closed),
            "points": [
                {
                    "x": number(vertex[0], precision),
                    "y": number(vertex[1], precision),
                    "bulge": number(vertex[4] if len(vertex) > 4 else 0, precision),
                }
                for vertex in entity.get_points()
            ],
        }
    if dxftype == "POLYLINE":
        return {
            **base,
            "closed": bool(entity.is_closed),
            "points": [point(vertex.dxf.location, precision) for vertex in entity.vertices],
        }
    if dxftype == "INSERT":
        return {
            **base,
            "block": entity.dxf.name,
            "insert": point(entity.dxf.insert, precision),
            "rotation": number(getattr(entity.dxf, "rotation", 0), precision),
            "xscale": number(getattr(entity.dxf, "xscale", 1), precision),
            "yscale": number(getattr(entity.dxf, "yscale", 1), precision),
        }
    if dxftype == "TEXT":
        return {
            **base,
            "text": normalize_text(entity.dxf.text),
            "insert": point(entity.dxf.insert, precision),
            "height": number(getattr(entity.dxf, "height", 0), precision),
            "rotation": number(getattr(entity.dxf, "rotation", 0), precision),
        }
    if dxftype == "MTEXT":
        return {
            **base,
            "text": normalize_text(entity.text),
            "insert": point(entity.dxf.insert, precision),
            "char_height": number(getattr(entity.dxf, "char_height", 0), precision),
        }
    if dxftype == "DIMENSION":
        measurement = None
        try:
            measurement = number(entity.get_measurement(), precision)
        except Exception:
            pass
        return {
            **base,
            "dimtype": int(getattr(entity.dxf, "dimtype", 0)),
            "measurement": measurement,
        }

    return None


def extract_points(canonical: dict[str, Any]) -> Iterable[tuple[float, float, float]]:
    for key in ("start", "end", "center", "insert"):
        if key in canonical:
            yield tuple(canonical[key])
    for vertex in canonical.get("points", []):
        if isinstance(vertex, dict):
            yield (float(vertex.get("x", 0)), float(vertex.get("y", 0)), 0.0)
        else:
            yield tuple(vertex)


def bounding_box(points: list[tuple[float, float, float]], precision: int) -> Optional[dict[str, list[float]]]:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] if len(p) > 2 else 0.0 for p in points]
    return {
        "min": [number(min(xs), precision), number(min(ys), precision), number(min(zs), precision)],
        "max": [number(max(xs), precision), number(max(ys), precision), number(max(zs), precision)],
    }


def point(value, precision: int) -> list[float]:
    return [number(value[0], precision), number(value[1], precision), number(value[2] if len(value) > 2 else 0, precision)]


def number(value: Any, precision: int) -> float:
    rounded = round(float(value), precision)
    return 0.0 if rounded == -0.0 else rounded


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def safe_temp_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    stem = Path(filename).stem or "drawing"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "drawing"
    safe_suffix = suffix if suffix in SUPPORTED_EXTENSIONS else ".dxf"
    return f"{safe_stem}{safe_suffix}"


def detect_drawing_code(filename: str, data: bytes) -> Optional[str]:
    candidates = [filename]
    try:
        sample = data[:20000].decode("latin-1", errors="ignore")
        candidates.append(sample)
    except Exception:
        pass

    patterns = [
        r"\b[A-Z]{2,6}[-_ ]?\d{3,8}[A-Z]?\b",
        r"\b\d{4,8}[-_ ][A-Z]{1,5}\b",
    ]
    for text in candidates:
        upper_text = text.upper()
        for pattern in patterns:
            match = re.search(pattern, upper_text)
            if match:
                return re.sub(r"\s+", "", match.group(0))
    return None


def cleanup_empty_dirs(path: Path) -> None:
    try:
        if path.exists() and not any(path.iterdir()):
            shutil.rmtree(path)
    except OSError:
        pass
