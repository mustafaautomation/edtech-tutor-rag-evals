"""Labelled questions for the evaluation gate."""

import json
from pathlib import Path

from harborlight_tutor.answering import (
    OFF_SYLLABUS_RESPONSE,
    UNKNOWN_RESPONSE,
    classify,
)
from harborlight_tutor.corpus import Catalog
from harborlight_tutor.models import Behavior, EvalQuestion, RefuseKind

_BEHAVIORS = {"answer", "hint", "refuse"}
_REFUSE_KINDS = {"", "off_syllabus", "unknown"}


def load_questions(path: Path, catalog: Catalog) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"{path}:{line_number} is not an object")
        questions.append(_parse(raw, line_number))
    if not 30 <= len(questions) <= 50:
        raise ValueError(f"expected 30 to 50 questions, found {len(questions)}")
    ids = [question.id for question in questions]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate question ids")
    _validate(questions, catalog)
    return questions


def _parse(raw: dict[str, object], line_number: int) -> EvalQuestion:
    behavior = raw.get("expected_behavior")
    refuse_kind = raw.get("refuse_kind", "")
    if behavior not in _BEHAVIORS:
        raise ValueError(f"line {line_number} has a bad expected_behavior")
    if refuse_kind not in _REFUSE_KINDS:
        raise ValueError(f"line {line_number} has a bad refuse_kind")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError(f"line {line_number} tags must be a list of strings")
    return EvalQuestion(
        id=str(raw["id"]),
        question=str(raw["question"]),
        expected_behavior=_as_behavior(behavior),
        refuse_kind=_as_refuse_kind(refuse_kind),
        reference_answer=str(raw["reference_answer"]),
        reference_context_ids=tuple(str(item) for item in _as_list(raw["reference_context_ids"])),
        must_include=tuple(str(item) for item in _as_list(raw["must_include"])),
        must_not_include=tuple(str(item) for item in _as_list(raw.get("must_not_include", []))),
        grade_retrieval=bool(raw["grade_retrieval"]),
        tags=tuple(str(tag) for tag in tags),
    )


def _as_behavior(value: object) -> Behavior:
    if value == "answer" or value == "hint" or value == "refuse":
        return value
    raise ValueError(value)


def _as_refuse_kind(value: object) -> RefuseKind:
    if value == "" or value == "off_syllabus" or value == "unknown":
        return value
    raise ValueError(value)


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("expected a list")
    return value


def _expected_refusal(refuse_kind: RefuseKind) -> str:
    if refuse_kind == "off_syllabus":
        return OFF_SYLLABUS_RESPONSE
    if refuse_kind == "unknown":
        return UNKNOWN_RESPONSE
    raise ValueError(refuse_kind)


def _validate(questions: list[EvalQuestion], catalog: Catalog) -> None:
    corpus_text = "\n".join(chunk.text for chunk in catalog.chunks)
    folded_corpus = corpus_text.casefold()
    for phrase in (OFF_SYLLABUS_RESPONSE, UNKNOWN_RESPONSE):
        if phrase.casefold() in folded_corpus:
            raise ValueError(
                "a refusal sentence is written into the notes, so a dump can pass the gate"
            )
    for question in questions:
        for chunk_id in question.reference_context_ids:
            if chunk_id not in catalog.by_id:
                raise KeyError(f"{question.id} references missing chunk {chunk_id}")
        if question.grade_retrieval and not question.reference_context_ids:
            raise ValueError(f"{question.id} grades retrieval but has no reference context")
        if not question.grade_retrieval and question.reference_context_ids:
            raise ValueError(f"{question.id} has reference contexts but retrieval is not graded")
        decision = classify(question.question)
        if question.expected_behavior == "answer":
            if decision.type != "proceed":
                raise ValueError(
                    f"{question.id} is labelled answer but policy class is {decision.type}"
                )
            blob = "\n".join(catalog.by_id[cid].text for cid in question.reference_context_ids)
            for phrase in question.must_include:
                if phrase.casefold() not in blob.casefold():
                    raise ValueError(f"{question.id} phrase not in reference notes: {phrase}")
                if phrase.casefold() not in question.reference_answer.casefold():
                    raise ValueError(f"{question.id} phrase not in reference answer: {phrase}")
        elif question.expected_behavior == "hint":
            if decision.type != "problem_set" or decision.doc_id is None:
                raise ValueError(f"{question.id} is not classified as a problem set")
            hint = catalog.require(decision.doc_id, "graded_hint").text
            solution = catalog.require(decision.doc_id, "graded_solution").text
            for phrase in question.must_include:
                if phrase.casefold() not in hint.casefold():
                    raise ValueError(f"{question.id} hint is missing {phrase}")
                if phrase.casefold() in solution.casefold():
                    raise ValueError(f"{question.id} solution also contains hint phrase {phrase}")
            for phrase in question.must_not_include:
                if phrase.casefold() not in solution.casefold():
                    raise ValueError(f"{question.id} solution is missing forbidden phrase {phrase}")
                if phrase.casefold() in hint.casefold():
                    raise ValueError(f"{question.id} hint contains forbidden phrase {phrase}")
        else:
            if question.refuse_kind == "off_syllabus" and decision.type != "off_syllabus":
                raise ValueError(f"{question.id} was not classified as off-syllabus")
            if question.refuse_kind == "unknown" and decision.type != "proceed":
                raise ValueError(
                    f"{question.id} unknown question was classified as {decision.type}"
                )
            for phrase in question.must_include:
                if phrase.casefold() not in _expected_refusal(question.refuse_kind).casefold():
                    raise ValueError(f"{question.id} refusal phrase is not the canned response")
