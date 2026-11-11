"""Retrieval wrappers and the RAG pipeline."""

from collections.abc import Sequence
from typing import Protocol

from harborlight_tutor.answering import select_shown
from harborlight_tutor.corpus import Catalog
from harborlight_tutor.faiss_index import FaissIndex
from harborlight_tutor.models import Chunk, Mode, PipelineOutput, RetrievedChunk
from harborlight_tutor.prompts import render_user_prompt
from harborlight_tutor.providers import LLMProvider


class Retriever(Protocol):
    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]: ...


DECOY_CHUNK_ID = "not-covered#unrelated-page"
VARIANT_ORDER = ("improved", "no_guardrail", "bad_retriever")


def indexable_chunks(chunks: Sequence[Chunk]) -> list[Chunk]:
    """Keep graded solutions out of the index so retrieval cannot surface them."""
    return [chunk for chunk in chunks if chunk.kind != "graded_solution"]


class EmbeddingRetriever:
    def __init__(self, index: FaissIndex) -> None:
        self._index = index

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return self._index.search(query, k)


class BadRetriever:
    """Returns one fixed unrelated note for every query. Used to prove the gate fails."""

    def __init__(self, decoys: Sequence[Chunk]) -> None:
        if not decoys:
            raise ValueError("bad retriever needs at least one decoy chunk")
        self._decoys = list(decoys)

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        del query
        chosen = self._decoys[: max(k, 0)]
        return [RetrievedChunk(chunk=chunk, score=0.0) for chunk in chosen]


class Pipeline:
    def __init__(
        self,
        *,
        retriever: Retriever,
        provider: LLMProvider,
        catalog: Catalog,
        mode: Mode,
        variant: str,
        top_k: int,
        system_prompt: str,
    ) -> None:
        self._retriever = retriever
        self._provider = provider
        self._catalog = catalog
        self._mode: Mode = mode
        self.variant = variant
        self._top_k = top_k
        self.system_prompt = system_prompt

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def answer(self, question: str, question_id: str = "") -> PipelineOutput:
        retrieved = tuple(self._retriever.retrieve(question, self._top_k))
        shown = tuple(select_shown(question, retrieved, self._catalog, self._mode))
        user = render_user_prompt(question, shown)
        response = self._provider.generate(system=self.system_prompt, user=user)
        return PipelineOutput(
            question_id=question_id,
            question=question,
            response=response,
            retrieved=retrieved,
            shown=shown,
            variant=self.variant,
            provider=self._provider.name,
        )
