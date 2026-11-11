"""Shared records for notes, retrieval, and labelled questions."""

from dataclasses import dataclass, field
from typing import Literal

Behavior = Literal["answer", "hint", "refuse"]
RefuseKind = Literal["", "off_syllabus", "unknown"]
Mode = Literal["guarded", "unguarded"]


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    title: str
    section: str
    text: str
    kind: str


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    expected_behavior: Behavior
    refuse_kind: RefuseKind
    reference_answer: str
    reference_context_ids: tuple[str, ...]
    must_include: tuple[str, ...]
    must_not_include: tuple[str, ...]
    grade_retrieval: bool
    tags: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PipelineOutput:
    question_id: str
    question: str
    response: str
    retrieved: tuple[RetrievedChunk, ...]
    shown: tuple[Chunk, ...]
    variant: str
    provider: str

    @property
    def retrieved_ids(self) -> list[str]:
        return [item.chunk.id for item in self.retrieved]

    @property
    def shown_ids(self) -> list[str]:
        return [chunk.id for chunk in self.shown]

    @property
    def retrieved_texts(self) -> list[str]:
        return [item.chunk.text for item in self.retrieved]
