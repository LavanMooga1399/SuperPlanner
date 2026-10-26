"""API-only request bodies of `/api/v1/mfg` (M1-DESIGN 9.3, 9.4); entity bodies are the `mfg.model` Inputs."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ...mfg.model import Code, Revision


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseRequest(_Strict):
    effective_from: date | None = None
    supersede_previous: bool = False


class EmptyRequest(_Strict):
    pass


class BomCopyRequest(_Strict):
    revision: Revision | None = None


class RoutingCopyRequest(_Strict):
    revision: Revision | None = None
    code: Code | None = None


class SheetMapping(_Strict):
    target: str | None = None
    columns: dict[str, str | None] = Field(default_factory=dict)


class ImportOptionsModel(_Strict):
    replace_children: bool = True
    release: bool = False
    default_effective_from: date | None = None


class ImportMappingRequest(_Strict):
    sheets: Annotated[dict[str, SheetMapping], Field(max_length=200)]
    options: ImportOptionsModel = Field(default_factory=ImportOptionsModel)


class SampleLoadRequest(_Strict):
    replace: bool = False


class ResetRequest(_Strict):
    confirm: str = Field(default="", max_length=100)
