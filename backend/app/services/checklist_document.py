"""Checklist *document*: the UI's JSON format (see docs/API_CONTRACT.md).

The document is the source of truth the UI edits; the backend derives its normalised
`Criterion` rows from it and keeps the document itself per version so the UI can render old
evaluations exactly as they were scored.
"""

import json
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.config import BACKEND_ROOT
from app.models import Checklist
from app.schemas.checklist import ChecklistIn, CriterionIn, ScaleStep

DEFAULT_DOCUMENT_PATH = BACKEND_ROOT / "data" / "checklist.default.json"

TYPE_TO_ANSWER = {"binary": "yes_no", "scale": "scale", "flag": "yes_no"}


class DocumentError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class DocSection(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class DocScaleStep(BaseModel):
    value: float
    label: str = ""


class DocCriterion(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_\-]+$")
    code: str = ""
    section: str | None = None
    name: str = ""
    type: str = "binary"  # binary | scale | flag
    weight: float = 0
    na_allowed: bool = False
    description: str = ""
    na_condition: str | None = None
    scale: list[DocScaleStep] | None = None


class ChecklistDocument(BaseModel):
    """Lenient shape: unknown keys are kept and returned untouched."""

    model_config = {"extra": "allow"}

    id: str = "chat-quality"
    name: str = ""
    version: int | None = None
    rules: dict[str, Any] = Field(default_factory=lambda: {"rounding": 2})
    sections: list[DocSection] = Field(default_factory=list)
    criteria: list[DocCriterion] = Field(min_length=1)


@lru_cache
def load_default_document() -> dict[str, Any]:
    with open(DEFAULT_DOCUMENT_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate_document(raw: dict[str, Any]) -> ChecklistDocument:
    """Same rules the UI applies before saving (frontend/js/scoring.js::validateChecklist)."""
    try:
        doc = ChecklistDocument.model_validate(raw)
    except ValidationError as exc:
        raise DocumentError(
            [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        ) from exc

    errors: list[str] = []
    if not doc.name.strip():
        errors.append("name: checklist name is required")
    section_ids = {s.id for s in doc.sections}
    ids = [c.id for c in doc.criteria]
    if len(set(ids)) != len(ids):
        errors.append("criteria: ids must be unique")
    scored = [c for c in doc.criteria if c.type != "flag"]
    if not scored:
        errors.append("criteria: at least one scored (non-flag) criterion is required")
    total = sum(c.weight for c in scored)
    if abs(total - 100) > 0.001:
        errors.append(f"weights: scored criteria sum to {total:g}, must be 100")
    for c in doc.criteria:
        tag = f"criterion '{c.name or c.id}'"
        if c.type not in TYPE_TO_ANSWER:
            errors.append(f"{tag}: unknown type '{c.type}'")
            continue
        if not c.name.strip():
            errors.append(f"{tag}: name is required")
        if not c.description.strip():
            errors.append(f"{tag}: description (the rule for the model) is required")
        if c.type != "flag" and not c.weight > 0:
            errors.append(f"{tag}: weight must be greater than 0")
        if c.na_allowed and not (c.na_condition or "").strip():
            errors.append(f"{tag}: na_condition is required when N/A is allowed")
        if c.section and section_ids and c.section not in section_ids:
            errors.append(f"{tag}: unknown section '{c.section}'")
        if c.type == "scale":
            values = [s.value for s in (c.scale or [])]
            if len(values) < 2:
                errors.append(f"{tag}: a scale needs at least 2 steps")
            elif len(set(values)) != len(values):
                errors.append(f"{tag}: scale steps must be unique")
            elif not max(values) > 0:
                errors.append(f"{tag}: the top scale step must be greater than 0")
            elif any(v < 0 or v != int(v) for v in values):
                errors.append(f"{tag}: scale steps must be non-negative integers")
    if errors:
        raise DocumentError(errors)
    return doc


def document_to_checklist_in(raw: dict[str, Any]) -> ChecklistIn:
    doc = validate_document(raw)
    section_names = {s.id: s.name for s in doc.sections}
    criteria: list[CriterionIn] = []
    for c in doc.criteria:
        is_flag = c.type == "flag"
        steps = (
            sorted((int(s.value) for s in (c.scale or [])), reverse=True)
            if c.type == "scale"
            else []
        )
        labels = {int(s.value): s.label for s in (c.scale or [])}
        criteria.append(
            CriterionIn(
                code=c.id,
                title=c.name,
                rule=c.description,
                section=section_names.get(c.section or "", c.section),
                answer_type=TYPE_TO_ANSWER[c.type],
                scale_max=steps[0] if steps else None,
                scale_steps=[ScaleStep(value=v, label=labels.get(v, "")) for v in steps] or None,
                weight=0.0 if is_flag else c.weight,
                allow_na=bool(c.na_allowed) and not is_flag,
                na_rule=c.na_condition if c.na_allowed else None,
                is_flag=is_flag,
            )
        )
    return ChecklistIn(name=doc.name, description=None, criteria=criteria)


def document_from_checklist(checklist: Checklist) -> dict[str, Any]:
    """Fallback for checklists created without a UI document (e.g. from the CLI)."""
    return document_from_snapshot(
        {
            "name": checklist.name,
            "version": checklist.version,
            "criteria": [
                {
                    "code": c.code,
                    "position": c.position,
                    "title": c.title,
                    "rule": c.rule,
                    "section": c.section,
                    "answer_type": c.answer_type,
                    "scale_steps": c.scale_steps,
                    "weight": c.weight,
                    "allow_na": c.allow_na,
                    "na_rule": c.na_rule,
                    "is_flag": c.is_flag,
                }
                for c in checklist.criteria
            ],
        }
    )


def document_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """UI document for an evaluation: the stored one, or one derived from the snapshot."""
    doc = snapshot.get("document")
    if doc:
        return doc
    sections: list[dict[str, str]] = []
    section_id: dict[str, str] = {}
    criteria = []
    for i, c in enumerate(sorted(snapshot["criteria"], key=lambda x: x.get("position", 0)), 1):
        name = c.get("section") or "Критерии"
        if name not in section_id:
            section_id[name] = f"s{len(sections) + 1}"
            sections.append({"id": section_id[name], "name": name})
        item: dict[str, Any] = {
            "id": c["code"],
            "code": f"{i:02d}",
            "section": section_id[name],
            "name": c.get("title", c["code"]),
            "type": "flag"
            if c.get("is_flag")
            else ("scale" if c["answer_type"] == "scale" else "binary"),
            "weight": c.get("weight", 0),
            "na_allowed": bool(c.get("allow_na")),
            "description": c.get("rule", ""),
        }
        if c.get("allow_na"):
            item["na_condition"] = c.get("na_rule") or ""
        if c["answer_type"] == "scale":
            item["scale"] = [
                {"value": int(s["value"]), "label": s.get("label", "")}
                for s in (c.get("scale_steps") or [])
            ]
        criteria.append(item)
    return {
        "id": "chat-quality",
        "name": snapshot.get("name", ""),
        "version": snapshot.get("version"),
        "rules": {"rounding": 2},
        "sections": sections,
        "criteria": criteria,
    }
