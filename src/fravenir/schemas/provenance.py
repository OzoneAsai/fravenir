"""Schemas for provenance-preserving derived memory writes."""

from typing import Literal

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """One source node that supports a derived memory episode."""

    type: Literal["post", "thread", "episode"]
    id: int = Field(gt=0)
