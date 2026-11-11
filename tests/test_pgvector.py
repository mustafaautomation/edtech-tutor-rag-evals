from harborlight_tutor.corpus import load_corpus
from harborlight_tutor.paths import corpus_dir
from harborlight_tutor.pgvector_store import SEARCH_SQL, schema_statements
from harborlight_tutor.pipeline import indexable_chunks


def test_pgvector_sql_uses_cosine_distance() -> None:
    statements = schema_statements(384)
    assert any("CREATE EXTENSION IF NOT EXISTS vector" in statement for statement in statements)
    assert any("vector(384)" in statement for statement in statements)
    assert "<=>" in SEARCH_SQL
    assert "LIMIT %s" in SEARCH_SQL


def test_schema_rejects_a_bad_dimension() -> None:
    import pytest

    with pytest.raises(ValueError):
        schema_statements(0)


def test_indexable_chunks_drop_solutions() -> None:
    catalog = load_corpus(corpus_dir())
    kept = indexable_chunks(catalog.chunks)
    assert kept
    assert all(chunk.kind != "graded_solution" for chunk in kept)
    assert len(kept) < len(catalog.chunks)
