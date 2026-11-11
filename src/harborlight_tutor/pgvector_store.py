"""pgvector storage. Tests check the SQL; a live database is used only when a DSN is set."""

from collections.abc import Sequence
from typing import Any

from harborlight_tutor.embeddings import HashingEmbedder
from harborlight_tutor.models import Chunk, RetrievedChunk

TABLE = "stat101_chunks"

SEARCH_SQL = f"""
SELECT id, doc_id, kind, title, section, body,
       1 - (embedding <=> %s) AS score
FROM {TABLE}
ORDER BY embedding <=> %s
LIMIT %s
""".strip()

INSERT_SQL = f"""
INSERT INTO {TABLE} (id, doc_id, kind, title, section, body, embedding)
VALUES (%s, %s, %s, %s, %s, %s, %s)
""".strip()


def schema_statements(dim: int) -> list[str]:
    if not isinstance(dim, int) or dim <= 0 or dim > 4096:
        raise ValueError("dim must be an int from 1 to 4096")
    create = f"""
CREATE TABLE {TABLE} (
    id text PRIMARY KEY,
    doc_id text NOT NULL,
    kind text NOT NULL,
    title text NOT NULL,
    section text NOT NULL,
    body text NOT NULL,
    embedding vector({dim})
)
""".strip()
    return [
        "CREATE EXTENSION IF NOT EXISTS vector",
        f"DROP TABLE IF EXISTS {TABLE}",
        create,
    ]


class PgVectorIndex:
    def __init__(self, conn: Any, embedder: HashingEmbedder, chunks: Sequence[Chunk]) -> None:
        self._conn = conn
        self.embedder = embedder
        self.chunks = list(chunks)
        self.embedder.fit([chunk.text for chunk in self.chunks])
        vectors = self.embedder.embed([chunk.text for chunk in self.chunks])
        for statement in schema_statements(embedder.dim):
            self._conn.execute(statement)
        for chunk, vector in zip(self.chunks, vectors, strict=True):
            self._conn.execute(
                INSERT_SQL,
                (
                    chunk.id,
                    chunk.doc_id,
                    chunk.kind,
                    chunk.title,
                    chunk.section,
                    chunk.text,
                    vector.tolist(),
                ),
            )
        self._conn.commit()

    def search(self, query: str, k: int) -> list[RetrievedChunk]:
        vector = self.embedder.embed([query])[0].tolist()
        rows = self._conn.execute(SEARCH_SQL, (vector, vector, k)).fetchall()
        found: list[RetrievedChunk] = []
        for row in rows:
            chunk = Chunk(
                id=str(row[0]),
                doc_id=str(row[1]),
                title=str(row[3]),
                section=str(row[4]),
                text=str(row[5]),
                kind=str(row[2]),
            )
            found.append(RetrievedChunk(chunk=chunk, score=float(row[6])))
        return found


class PgVectorRetriever:
    def __init__(self, store: PgVectorIndex) -> None:
        self._store = store

    def retrieve(self, query: str, k: int) -> list[RetrievedChunk]:
        return self._store.search(query, k)


def connect(dsn: str) -> Any:
    import psycopg
    from pgvector.psycopg import register_vector

    conn = psycopg.connect(dsn)
    register_vector(conn)
    return conn
