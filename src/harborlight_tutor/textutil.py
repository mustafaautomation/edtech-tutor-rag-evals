"""Token helpers shared by the embedder and the extractive answerer."""

import re

_TOKEN = re.compile(r"[a-z0-9]+")

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "and",
        "or",
        "to",
        "in",
        "for",
        "on",
        "at",
        "by",
        "from",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "into",
        "over",
        "than",
        "then",
        "so",
        "if",
        "not",
        "no",
        "nor",
        "but",
        "what",
        "which",
        "who",
        "when",
        "where",
        "why",
        "how",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "may",
        "will",
        "we",
        "you",
        "your",
        "our",
        "their",
        "they",
        "them",
        "he",
        "she",
        "his",
        "her",
        "about",
        "also",
        "only",
        "other",
        "such",
        "each",
        "per",
        "within",
        "across",
        "using",
        "use",
        "used",
        "says",
        "say",
        "said",
        "called",
        "call",
    }
)


def content_tokens(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.casefold()) if token not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    """Split on sentence periods. Keep titles such as Dr. attached to the name."""
    protected = re.sub(
        r"\b(Dr|Mr|Ms|Mrs)\.",
        lambda match: match.group(0).replace(".", "\u0000"),
        text,
    )
    parts = re.split(r"(?<=[.])\s+", protected.strip())
    return [part.replace("\u0000", ".").strip() for part in parts if part.strip()]
