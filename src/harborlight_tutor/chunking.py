"""Character-window chunking with overlap, used when a section is longer than the window."""


def split_text(text: str, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """Split text into windows. Short text is returned as a single stripped piece."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be >= 0 and < max_chars")
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    parts: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + max_chars)
        if end < len(cleaned):
            space = cleaned.rfind(" ", start + 1, end)
            if space > start:
                end = space
        piece = cleaned[start:end].strip()
        if piece:
            parts.append(piece)
        if end >= len(cleaned):
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
    return parts
