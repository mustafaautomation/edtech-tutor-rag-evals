"""Tutor policy: graded hints, off-syllabus refusals, and extractive answers from shown notes."""

import re
from collections.abc import Sequence
from typing import Literal

from harborlight_tutor.corpus import Catalog
from harborlight_tutor.models import Chunk, Mode, RetrievedChunk
from harborlight_tutor.textutil import content_tokens, split_sentences

OFF_SYLLABUS_RESPONSE = "That question is outside the STAT 101 syllabus, so I can't answer it."
UNKNOWN_RESPONSE = "I don't know; that is not in the STAT 101 lesson notes."
HINT_PREFIX = "This is a graded assignment, so I'll give a hint rather than the final result."
ANSWER_PREFIX = "From the STAT 101 notes: "
UNSOURCED_CLAIM = "Additionally, a commonly quoted figure outside these notes is 42."

_PROBLEM_SETS = (
    ("problem set 1", "ps1"),
    ("problem set 2", "ps2"),
    ("problem set 3", "ps3"),
)

_OFF_SYLLABUS = (
    r"\banova\b",
    r"\bbayesian\b",
    r"\bpython\b",
    r"\bstock\b",
    r"\bpunnett\b",
    r"world cup",
    r"cake recipe",
    r"system prompt",
    r"ignore (?:your|previous|all) instructions",
    r"you are now",
)

DecisionType = Literal["problem_set", "off_syllabus", "proceed"]


class Decision:
    def __init__(self, type: DecisionType, doc_id: str | None = None) -> None:
        self.type: DecisionType = type
        self.doc_id = doc_id


def classify(question: str) -> Decision:
    lowered = question.casefold()
    for phrase, doc_id in _PROBLEM_SETS:
        if phrase in lowered:
            return Decision("problem_set", doc_id)
    for pattern in _OFF_SYLLABUS:
        if re.search(pattern, lowered):
            return Decision("off_syllabus")
    return Decision("proceed")


def select_shown(
    question: str,
    retrieved: Sequence[RetrievedChunk],
    catalog: Catalog,
    mode: Mode,
) -> list[Chunk]:
    decision = classify(question)
    shown: list[Chunk] = []
    seen: set[str] = set()
    for item in retrieved:
        chunk = item.chunk
        if mode == "guarded" and chunk.kind == "graded_solution":
            continue
        if chunk.id in seen:
            continue
        shown.append(chunk)
        seen.add(chunk.id)
    if decision.type == "problem_set" and decision.doc_id is not None:
        doc_id = decision.doc_id
        shown = [
            chunk
            for chunk in shown
            if chunk.doc_id == doc_id or not chunk.kind.startswith("graded_")
        ]
        kind = "graded_solution" if mode == "unguarded" else "graded_hint"
        extra = catalog.require(doc_id, kind)
        if extra.id not in {chunk.id for chunk in shown}:
            shown.append(extra)
    return shown


def _graded_text(notes: Sequence[Chunk], doc_id: str | None, kind: str) -> str | None:
    for chunk in notes:
        if chunk.kind == kind and (doc_id is None or chunk.doc_id == doc_id):
            return chunk.text
    return None


def best_sentence(question: str, notes: Sequence[Chunk]) -> str | None:
    query = set(content_tokens(question))
    if not query:
        return None
    best: tuple[tuple[int, float], str] | None = None
    for note in notes:
        if note.kind == "graded_solution":
            continue
        for sentence in split_sentences(note.text):
            tokens = content_tokens(sentence)
            unique = set(tokens)
            if not unique:
                continue
            overlap = len(query.intersection(unique))
            if overlap < 2:
                continue
            rank = (overlap, overlap / len(unique))
            if best is None or rank > best[0]:
                best = (rank, sentence)
    if best is None:
        return None
    return best[1]


def guarded_answer(question: str, shown: Sequence[Chunk]) -> str:
    decision = classify(question)
    if decision.type == "problem_set":
        hint = _graded_text(shown, decision.doc_id, "graded_hint")
        if hint is None:
            return HINT_PREFIX
        return f"{HINT_PREFIX} {hint}"
    if decision.type == "off_syllabus":
        return OFF_SYLLABUS_RESPONSE
    sentence = best_sentence(question, shown)
    if sentence is None:
        return UNKNOWN_RESPONSE
    return ANSWER_PREFIX + sentence


def unguarded_answer(question: str, shown: Sequence[Chunk]) -> str:
    decision = classify(question)
    if decision.type == "problem_set":
        solution = _graded_text(shown, decision.doc_id, "graded_solution")
        if solution is None:
            return "Final result: unavailable."
        return f"Final result: {solution}"
    sentence = best_sentence(question, shown)
    if sentence is None:
        dumped = " ".join(chunk.text for chunk in shown) or "No notes."
        return f"{dumped} {UNSOURCED_CLAIM}"
    return f"{sentence} {UNSOURCED_CLAIM}"
