from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base for request bodies: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class OutModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(OutModel):
    code: str
    message: str


class ErrorOut(OutModel):
    error: ErrorDetail
