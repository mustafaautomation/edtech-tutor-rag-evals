"""Generation providers. Offline runs use the deterministic tutor."""

import re
from typing import Any, Protocol

from harborlight_tutor.answering import guarded_answer, unguarded_answer
from harborlight_tutor.models import Chunk, Mode
from harborlight_tutor.prompts import GUARDED_SYSTEM, UNGUARDED_SYSTEM

_BLOCK = re.compile(r"\[id=(\S+) kind=(\S+)\]\n(.*?)(?=\n\[id=|\Z)", re.DOTALL)


class LLMProvider(Protocol):
    name: str

    def generate(self, *, system: str, user: str) -> str: ...


def parse_user_prompt(user: str) -> tuple[str, list[Chunk]]:
    marker = "\n\nRetrieved lesson notes:\n"
    if not user.startswith("Question:\n") or marker not in user:
        raise ValueError("user prompt is not in the tutor format")
    question, rest = user[len("Question:\n") :].split(marker, 1)
    shown: list[Chunk] = []
    for match in _BLOCK.finditer(rest):
        chunk_id = match.group(1)
        doc_id = chunk_id.split("#", 1)[0]
        shown.append(
            Chunk(
                id=chunk_id,
                doc_id=doc_id,
                title="",
                section="",
                text=match.group(3).strip(),
                kind=match.group(2),
            )
        )
    return question.strip(), shown


class DeterministicTutor:
    """Applies the written tutor policy without a network call.

    Guarded mode gives hints on graded work, refuses off-syllabus questions, and
    quotes a lesson sentence when one overlaps the question. Unguarded mode is
    the deliberately broken comparison: it returns graded solutions and adds an
    unsourced claim.
    """

    name = "deterministic"

    def __init__(self, mode: Mode) -> None:
        if mode not in ("guarded", "unguarded"):
            raise ValueError(mode)
        self.mode: Mode = mode

    def generate(self, *, system: str, user: str) -> str:
        question, shown = parse_user_prompt(user)
        if self.mode == "guarded":
            if system.strip() != GUARDED_SYSTEM:
                raise RuntimeError("guarded tutor received a different system prompt")
            return guarded_answer(question, shown)
        if system.strip() != UNGUARDED_SYSTEM:
            raise RuntimeError("unguarded tutor received a different system prompt")
        return unguarded_answer(question, shown)


class OpenAIProvider:
    name = "openai"

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def generate(self, *, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI returned an empty message")
        return content


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client: Any, model: str) -> None:
        self._client = client
        self._model = model

    def generate(self, *, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=800,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                parts.append(text)
        if not parts:
            raise RuntimeError("Anthropic returned an empty message")
        return "".join(parts)
