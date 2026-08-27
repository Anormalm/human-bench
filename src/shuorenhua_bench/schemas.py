from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Provenance(str, Enum):
    HUMAN = "human"
    RAW_MODEL = "raw_model"
    HUMANIZER = "humanizer"
    CONTROLLED = "controlled_perturbation"


class Scenario(StrictModel):
    scenario_id: str = Field(min_length=1)
    language: str
    genre: str
    relationship: str
    intent: str
    task_type: str
    channel: str
    context: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    required_facts: list[str] = Field(default_factory=list)
    prohibited_changes: list[str] = Field(default_factory=list)
    semantic_cluster_id: str | None = None
    source_template_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationManifest(StrictModel):
    provider: str | None = None
    model: str | None = None
    model_revision: str | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, gt=0, le=1)
    seed: int | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    input_hash: str | None = None
    output_hash: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Response(StrictModel):
    response_id: str = Field(min_length=1)
    scenario_id: str = Field(min_length=1)
    system_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    provenance: Provenance
    source_response_id: str | None = None
    author_id: str | None = None
    track: Literal["native_generation", "humanization"] = "native_generation"
    manifest: GenerationManifest | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def humanization_has_source(self) -> "Response":
        if self.track == "humanization" and not self.source_response_id:
            raise ValueError("humanization responses require source_response_id")
        return self


class Pair(StrictModel):
    pair_id: str
    scenario_id: str
    response_a: str
    response_b: str
    assignment_block: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def distinct_responses(self) -> "Pair":
        if self.response_a == self.response_b:
            raise ValueError("a response cannot be paired with itself")
        return self


class ProblemSpan(StrictModel):
    response_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    type: str
    severity: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def valid_range(self) -> "ProblemSpan":
        if self.end <= self.start:
            raise ValueError("span end must be greater than start")
        return self


class PairwiseJudgment(StrictModel):
    pair_id: str
    scenario_id: str
    annotator_id: str
    response_a: str
    response_b: str
    preference: Literal["A", "B", "tie"]
    action_a: Literal["send", "revise", "reject"]
    action_b: Literal["send", "revise", "reject"]
    confidence: int = Field(ge=1, le=5)
    duration_seconds: float | None = Field(default=None, ge=0)
    population: dict[str, str] = Field(default_factory=dict)
    spans: list[ProblemSpan] = Field(default_factory=list)

