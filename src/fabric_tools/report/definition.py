"""Pack and unpack Fabric report public definitions; parse/rewrite ``definition.pbir``."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from fabric_tools.definition_parts import (
    DefinitionPartsError,
    decode_part,
)
from fabric_tools.definition_parts import (
    pack_definition as pack_folder_definition,
)
from fabric_tools.definition_parts import (
    unpack_definition as unpack_folder_definition,
)
from fabric_tools.semantic_model.definition import (
    DefinitionError as SemanticModelDefinitionError,
)
from fabric_tools.semantic_model.definition import (
    detect_semantic_model_path,
    validate_local_semantic_model,
)

PBIR_PART = "definition.pbir"
REPORT_JSON_PART = "report.json"
DEFINITION_DIR = "definition"
PLATFORM_PART = ".platform"

_SEMANTIC_MODEL_ID_RE = re.compile(
    r"semanticmodelid\s*=\s*([0-9a-fA-F-]{36})",
    re.IGNORECASE,
)


class ReportFormat(str, Enum):
    PBIR = "PBIR"
    PBIR_LEGACY = "PBIR-Legacy"


class DefinitionError(ValueError):
    """Invalid local report path or definition payload."""


BindKind = Literal["byPath", "byConnection", "none"]


@dataclass(frozen=True)
class DatasetReference:
    """Parsed ``definition.pbir`` dataset binding."""

    kind: BindKind
    by_path: str | None = None
    connection_string: str | None = None
    semantic_model_id: str | None = None


@dataclass(frozen=True)
class LocalJoin:
    """Local report folder plus optional packable sibling semantic model."""

    report_path: Path
    model_path: Path | None
    reference: DatasetReference


def is_report_folder_name(name: str) -> bool:
    """True when *name* looks like a Fabric Git ``*.Report`` folder."""
    return name.endswith(".Report") or name.endswith(".report")


def is_pbix_path(path: Path | str) -> bool:
    """True when *path* points at a ``.pbix`` file (by suffix)."""
    return Path(path).suffix.lower() == ".pbix"


def detect_report_path(path: Path | str) -> Path:
    """Resolve *path* as a report folder path (does not fully validate)."""
    p = Path(path)
    if is_pbix_path(p):
        raise DefinitionError(
            f"Unsupported report folder path '{p}' (.pbix is not a Fabric definition "
            "folder; use PBIX import/export ops instead)."
        )
    if is_report_folder_name(p.name):
        return p
    if p.is_dir() and (p / PBIR_PART).is_file():
        return p
    raise DefinitionError(
        f"Unsupported report path '{p}'. Expected a *.Report folder "
        f"(with {PBIR_PART} and PBIR definition/ or PBIR-Legacy {REPORT_JSON_PART})."
    )


def display_name_from_path(path: Path | str) -> str:
    """Default Fabric display name from a local ``*.Report`` folder or ``.pbix`` stem."""
    p = Path(path)
    name = p.name
    if name.endswith(".Report"):
        return name[: -len(".Report")]
    if name.endswith(".report"):
        return name[: -len(".report")]
    if is_pbix_path(p):
        return p.stem
    return p.name


def detect_format(path: Path | str) -> ReportFormat:
    """Infer PBIR vs PBIR-Legacy from a validated report folder."""
    folder = validate_local_report(path)
    if (folder / DEFINITION_DIR).is_dir() and any(
        p.is_file() for p in (folder / DEFINITION_DIR).rglob("*")
    ):
        return ReportFormat.PBIR
    return ReportFormat.PBIR_LEGACY


def validate_local_report(path: Path | str) -> Path:
    """Ensure *path* is a packable report folder; return the folder path."""
    folder = detect_report_path(path)
    if not folder.is_dir():
        raise DefinitionError(f"Report folder not found: {folder}")
    pbir = folder / PBIR_PART
    if not pbir.is_file():
        raise DefinitionError(f"Report folder is missing '{PBIR_PART}': {folder}")
    try:
        load_pbir(folder)
    except DefinitionError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DefinitionError(f"invalid {PBIR_PART} in {folder}: {exc}") from exc

    has_pbir_dir = (folder / DEFINITION_DIR).is_dir() and any(
        p.is_file() for p in (folder / DEFINITION_DIR).rglob("*")
    )
    has_legacy = (folder / REPORT_JSON_PART).is_file()
    if has_pbir_dir and has_legacy:
        raise DefinitionError(
            f"report folder has both '{DEFINITION_DIR}/' and '{REPORT_JSON_PART}' "
            f"(use one format): {folder}"
        )
    if not has_pbir_dir and not has_legacy:
        raise DefinitionError(
            f"report folder needs '{DEFINITION_DIR}/' (PBIR) or '{REPORT_JSON_PART}' "
            f"(PBIR-Legacy): {folder}"
        )
    return folder


def load_pbir(path: Path | str) -> dict[str, Any]:
    """Load and parse ``definition.pbir`` from a report folder."""
    folder = Path(path)
    pbir_path = folder / PBIR_PART if folder.is_dir() else folder
    try:
        text = pbir_path.read_text(encoding="utf-8-sig")
        data = json.loads(text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DefinitionError(f"invalid {PBIR_PART}: {exc}") from exc
    if not isinstance(data, dict):
        raise DefinitionError(f"{PBIR_PART} must be a JSON object")
    return data


def parse_dataset_reference(pbir: dict[str, Any]) -> DatasetReference:
    """Parse ``datasetReference`` from a ``definition.pbir`` object."""
    ref = pbir.get("datasetReference")
    if not isinstance(ref, dict):
        return DatasetReference(kind="none")

    by_path = ref.get("byPath")
    if isinstance(by_path, dict):
        path = by_path.get("path")
        if isinstance(path, str) and path.strip():
            return DatasetReference(kind="byPath", by_path=path.strip())

    by_connection = ref.get("byConnection")
    if isinstance(by_connection, dict):
        conn = by_connection.get("connectionString")
        conn_str = conn.strip() if isinstance(conn, str) else None
        model_id = None
        if conn_str:
            match = _SEMANTIC_MODEL_ID_RE.search(conn_str)
            if match:
                model_id = match.group(1)
        if model_id is None:
            raw_id = by_connection.get("pbiServiceModelId") or by_connection.get(
                "semanticModelId"
            )
            if isinstance(raw_id, str) and raw_id.strip():
                model_id = raw_id.strip()
        return DatasetReference(
            kind="byConnection",
            connection_string=conn_str,
            semantic_model_id=model_id,
        )

    return DatasetReference(kind="none")


def rewrite_pbir_to_by_connection(
    pbir: dict[str, Any],
    semantic_model_id: str,
) -> dict[str, Any]:
    """Return a copy of *pbir* bound via ``byConnection`` to *semantic_model_id*."""
    if not semantic_model_id.strip():
        raise DefinitionError("semantic_model_id is required for byConnection rewrite")
    updated = json.loads(json.dumps(pbir))
    updated["datasetReference"] = {
        "byConnection": {
            "connectionString": f"semanticmodelid={semantic_model_id.strip()}",
        }
    }
    return updated


def write_pbir(folder: Path | str, pbir: dict[str, Any]) -> Path:
    """Write ``definition.pbir`` into a report folder."""
    dest = Path(folder)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / PBIR_PART
    path.write_text(
        json.dumps(pbir, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def resolve_local_join(path: Path | str) -> LocalJoin:
    """Validate a report folder and resolve a packable sibling semantic model if any.

    Join is packable when ``byPath`` resolves to a valid ``*.SemanticModel`` folder,
    or when a same-stem sibling ``*.SemanticModel`` exists next to the report.
    ``byConnection`` alone is not a local packable join (thin / live-connect).
    """
    report = validate_local_report(path)
    reference = parse_dataset_reference(load_pbir(report))
    model_path: Path | None = None

    if reference.kind == "byPath" and reference.by_path:
        candidate = (report / reference.by_path).resolve()
        try:
            model_path = validate_local_semantic_model(candidate)
        except SemanticModelDefinitionError as exc:
            raise DefinitionError(
                f"report byPath '{reference.by_path}' is not a packable semantic "
                f"model: {exc}"
            ) from exc
    else:
        sibling = _sibling_semantic_model_candidate(report)
        if sibling is not None:
            try:
                model_path = validate_local_semantic_model(sibling)
            except SemanticModelDefinitionError:
                model_path = None

    return LocalJoin(report_path=report, model_path=model_path, reference=reference)


def packable_local_model(path: Path | str) -> Path | None:
    """Return the sibling/byPath semantic model folder when joinable, else ``None``."""
    join = resolve_local_join(path)
    return join.model_path


def pack_definition(
    path: Path | str,
    *,
    pbir_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Fabric report definition from a local folder.

    When *pbir_override* is set, pack using that ``definition.pbir`` content instead
    of the on-disk file (used after byConnection rewrite for joined deploy).
    """
    folder = validate_local_report(path)
    fmt = detect_format(folder)
    if pbir_override is not None:
        # Pack from a temporary in-memory substitution: write override beside a
        # copy is expensive; instead pack folder then replace the pbir part.
        try:
            definition = pack_folder_definition(folder, format=fmt.value)
        except DefinitionPartsError as exc:
            raise DefinitionError(str(exc)) from exc
        payload = json.dumps(pbir_override, indent=2, ensure_ascii=False).encode(
            "utf-8"
        )
        parts = []
        replaced = False
        for part in definition.get("parts") or []:
            if isinstance(part, dict) and str(part.get("path")) == PBIR_PART:
                from fabric_tools.definition_parts import encode_part

                parts.append(encode_part(PBIR_PART, payload))
                replaced = True
            else:
                parts.append(part)
        if not replaced:
            from fabric_tools.definition_parts import encode_part

            parts.append(encode_part(PBIR_PART, payload))
        definition = {**definition, "parts": parts}
        return definition

    try:
        return pack_folder_definition(folder, format=fmt.value)
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc


def unpack_definition(definition: dict[str, Any], destination: Path | str) -> Path:
    """Write a Fabric definition response to a local report folder."""
    try:
        return unpack_folder_definition(definition, destination)
    except DefinitionPartsError as exc:
        raise DefinitionError(str(exc)) from exc


def definition_has_platform(definition: dict[str, Any]) -> bool:
    """True when the definition includes a ``.platform`` part."""
    parts = definition.get("parts") or []
    for part in parts:
        if (
            isinstance(part, dict)
            and Path(str(part.get("path", ""))).name == PLATFORM_PART
        ):
            return True
    return False


def part_payloads(definition: dict[str, Any]) -> dict[str, bytes]:
    """Decode definition parts to a ``{relative_path: bytes}`` map."""
    parts = definition.get("parts")
    if not isinstance(parts, list) or not parts:
        raise DefinitionError("Definition response has no parts")
    out: dict[str, bytes] = {}
    for part in parts:
        try:
            path, payload = decode_part(part)
        except DefinitionPartsError as exc:
            raise DefinitionError(str(exc)) from exc
        out[path.replace("\\", "/")] = payload
    return out


def folder_payloads(path: Path | str) -> dict[str, bytes]:
    """Read all files under a local report folder as relative-path payloads."""
    folder = validate_local_report(path)
    payloads: dict[str, bytes] = {}
    for file_path in sorted(folder.rglob("*"), key=lambda p: p.as_posix().lower()):
        if file_path.is_file():
            payloads[file_path.relative_to(folder).as_posix()] = file_path.read_bytes()
    return payloads


def definition_to_diff_text(definition: dict[str, Any]) -> str:
    """Stable multi-file text used for unified diffs of a Fabric definition."""
    return payloads_to_diff_text(part_payloads(definition))


def folder_to_diff_text(path: Path | str) -> str:
    """Stable multi-file text for unified diffs of a local report folder."""
    return payloads_to_diff_text(folder_payloads(path))


def payloads_to_diff_text(payloads: dict[str, bytes]) -> str:
    """Render part payloads as a deterministic multi-section text blob."""
    chunks: list[str] = []
    for name in sorted(payloads):
        chunks.append(f"=== {name} ===\n")
        chunks.append(_normalize_part_text(name, payloads[name]))
    return "".join(chunks)


def _normalize_part_text(name: str, payload: bytes) -> str:
    lower = name.lower()
    # Skip noisy binary-ish resources in StaticResources (images, etc.).
    if lower.startswith("staticresources/") and not lower.endswith(".json"):
        return f"<binary {len(payload)} bytes>\n"
    try:
        text = payload.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return f"<binary {len(payload)} bytes>\n"
    if (
        lower.endswith(".json")
        or lower.endswith(".pbir")
        or lower.endswith(".pbism")
        or lower.endswith(".bim")
    ):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return text if text.endswith("\n") else text + "\n"
        return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    return text if text.endswith("\n") else text + "\n"


def _sibling_semantic_model_candidate(report: Path) -> Path | None:
    stem = display_name_from_path(report)
    parent = report.parent
    for name in (f"{stem}.SemanticModel", f"{stem}.semanticmodel"):
        candidate = parent / name
        if candidate.is_dir():
            try:
                detect_semantic_model_path(candidate)
            except SemanticModelDefinitionError:
                continue
            return candidate
    return None
