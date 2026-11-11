"""Load markdown lesson notes into chunks."""

import re
from pathlib import Path

import yaml

from harborlight_tutor.chunking import split_text
from harborlight_tutor.models import Chunk

_KIND_COMMENT = re.compile(r"<!--\s*kind:\s*([a-z0-9_-]+)\s*-->", re.IGNORECASE)
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
_GRADED_KINDS = {
    "problem": "graded_problem",
    "hint": "graded_hint",
    "solution": "graded_solution",
}


def slug(title: str) -> str:
    dashed = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-")
    if not dashed:
        raise ValueError(f"cannot slug {title!r}")
    return dashed


class Catalog:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.by_id = {chunk.id: chunk for chunk in chunks}
        if len(self.by_id) != len(self.chunks):
            raise ValueError("duplicate chunk ids")

    def require(self, doc_id: str, kind: str) -> Chunk:
        matches = [chunk for chunk in self.chunks if chunk.doc_id == doc_id and chunk.kind == kind]
        if len(matches) != 1:
            raise KeyError(f"{doc_id} {kind}: found {len(matches)}")
        return matches[0]

    @property
    def doc_ids(self) -> set[str]:
        return {chunk.doc_id for chunk in self.chunks}


def load_corpus(directory: Path) -> Catalog:
    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise FileNotFoundError(f"no markdown notes in {directory}")
    chunks: list[Chunk] = []
    for path in paths:
        chunks.extend(_load_file(path))
    return Catalog(chunks)


def _load_file(path: Path) -> list[Chunk]:
    raw = path.read_text(encoding="utf-8")
    meta, body = _frontmatter(raw, path)
    doc_id = str(meta["id"])
    title = str(meta["title"])
    doc_kind = str(meta["kind"])
    chunks: list[Chunk] = []
    for section, text in _sections(body, path):
        kind = _section_kind(doc_kind, section, text)
        visible = _KIND_COMMENT.sub("", text).strip()
        pieces = split_text(visible)
        for index, piece in enumerate(pieces):
            section_slug = slug(section)
            suffix = section_slug if len(pieces) == 1 else f"{section_slug}-{index + 1}"
            chunks.append(
                Chunk(
                    id=f"{doc_id}#{suffix}",
                    doc_id=doc_id,
                    title=title,
                    section=section,
                    text=piece,
                    kind=kind,
                )
            )
    return chunks


def _frontmatter(raw: str, path: Path) -> tuple[dict[str, object], str]:
    if not raw.startswith("---\n"):
        raise ValueError(f"{path} is missing frontmatter")
    end = raw.find("\n---\n", 4)
    if end < 0:
        raise ValueError(f"{path} has unterminated frontmatter")
    loaded = yaml.safe_load(raw[4:end])
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} frontmatter must be a mapping")
    for key in ("id", "title", "kind"):
        if key not in loaded:
            raise ValueError(f"{path} frontmatter missing {key}")
    body = raw[end + 5 :]
    return loaded, body


def _sections(body: str, path: Path) -> list[tuple[str, str]]:
    matches = list(_HEADING.finditer(body))
    if not matches:
        raise ValueError(f"{path} has no sections")
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1).strip(), body[start:end].strip()))
    return sections


def _section_kind(doc_kind: str, section: str, body: str) -> str:
    comment = _KIND_COMMENT.search(body)
    if comment:
        return comment.group(1)
    if doc_kind == "graded":
        key = slug(section)
        if key not in _GRADED_KINDS:
            raise ValueError(f"graded section {section!r} is not problem, hint, or solution")
        return _GRADED_KINDS[key]
    return doc_kind
