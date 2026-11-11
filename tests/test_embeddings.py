import math

import numpy as np
import pytest

from harborlight_tutor.chunking import split_text
from harborlight_tutor.embeddings import HashingEmbedder, OpenAIEmbedder


def test_sentence_split_keeps_dr_with_the_name() -> None:
    from harborlight_tutor.textutil import split_sentences

    parts = split_sentences("The instructor is Dr. Lena Okonkwo. She teaches statistics.")
    assert parts[0] == "The instructor is Dr. Lena Okonkwo."


def test_split_text_keeps_short_passages() -> None:
    assert split_text("The median is the middle value.") == ["The median is the middle value."]


def test_split_text_windows_overlap_and_cover_the_source() -> None:
    text = " ".join(f"word{i}" for i in range(40))
    parts = split_text(text, max_chars=40, overlap=10)
    assert len(parts) > 1
    assert all(len(part) <= 40 for part in parts)
    assert parts[0].split()[0] == "word0"
    assert parts[-1].split()[-1] == "word39"


def test_split_text_rejects_bad_windows() -> None:
    with pytest.raises(ValueError):
        split_text("hello", max_chars=10, overlap=10)
    with pytest.raises(ValueError):
        split_text("hello", max_chars=0, overlap=0)


def test_hashing_embedder_is_deterministic_and_normalized() -> None:
    embedder = HashingEmbedder(32).fit(["alpha beta", "gamma delta"])
    first = embedder.embed(["alpha beta"])
    second = embedder.embed(["alpha beta"])
    assert first.shape == (1, 32)
    assert np.allclose(first, second)
    assert math.isclose(float(np.linalg.norm(first)), 1.0, rel_tol=1e-5)


def test_hashing_embedder_requires_fit() -> None:
    with pytest.raises(RuntimeError):
        HashingEmbedder(16).embed(["alpha"])


def test_related_text_outranks_unrelated_text() -> None:
    notes = [
        "The interquartile range is the third quartile minus the first quartile.",
        "A Type I error is rejecting a true null hypothesis.",
        "The binomial mean is the number of trials times the success probability.",
    ]
    embedder = HashingEmbedder(128).fit(notes)
    vectors = embedder.embed(notes)
    query = embedder.embed(["What is the interquartile range?"])[0]
    scores = vectors @ query
    assert int(np.argmax(scores)) == 0


def test_openai_embedder_normalizes_provider_vectors() -> None:
    class Item:
        def __init__(self, index: int, embedding: list[float]) -> None:
            self.index = index
            self.embedding = embedding

    class Response:
        data = [Item(1, [0.0, 4.0]), Item(0, [3.0, 0.0])]

    class Client:
        def __init__(self) -> None:
            self.embeddings = self

        def create(self, model: str, input: list[str]) -> Response:
            assert model == "text-embedding-3-small"
            assert input == ["a", "b"]
            return Response()

    matrix = OpenAIEmbedder(Client(), "text-embedding-3-small").embed(["a", "b"])
    assert matrix.shape == (2, 2)
    assert np.allclose(matrix[0], [1.0, 0.0])
    assert np.allclose(matrix[1], [0.0, 1.0])
