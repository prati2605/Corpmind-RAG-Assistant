"""Page-aware chunking.

Each segment (a page, or a CSV row group) is split on its own, so a chunk never spans two
pages and its citation page number is always exact. Within a segment, LangChain's
RecursiveCharacterTextSplitter splits on paragraphs first, then lines, then sentences,
then words, so chunks break at natural boundaries. Overlap keeps context that straddles a split.

Very short segment tails (< MIN_CHUNK_CHARS) are merged into the previous chunk from the same
page instead of becoming useless one-line chunks.
"""
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings
from app.services.ingestion.parsers import Segment

MIN_CHUNK_CHARS = 40


@dataclass
class ChunkData:
    index: int
    text: str
    page: int | None
    section: str | None


def make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", "; ", ", ", " ", ""],
        keep_separator="end",
        strip_whitespace=True,
    )


def chunk_segments(segments: list[Segment]) -> list[ChunkData]:
    splitter = make_splitter()
    chunks: list[ChunkData] = []
    for seg in segments:
        pieces = [p.strip() for p in splitter.split_text(seg.text) if p.strip()]
        for piece in pieces:
            prev = chunks[-1] if chunks else None
            if (len(piece) < MIN_CHUNK_CHARS and prev is not None and prev.page == seg.page
                    and prev.section == seg.section):
                prev.text = f"{prev.text}\n{piece}"
                continue
            chunks.append(ChunkData(index=len(chunks), text=piece, page=seg.page, section=seg.section))
    return chunks
