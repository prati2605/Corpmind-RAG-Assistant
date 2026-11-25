import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class HistoryItem(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class SearchFilters(BaseModel):
    category_ids: list[int] | None = Field(default=None, max_length=20)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=10)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[HistoryItem] = Field(default_factory=list, max_length=20)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class CitationOut(BaseModel):
    index: int
    chunk_id: str
    document_id: str
    title: str
    page: int | None
    section: str | None
    snippet: str
    relevance: float


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    grounded: bool
    mode: str
    standalone_question: str
    rewritten: bool
    confidence: float
    confidence_label: str
    retrieval: dict
    latency_ms: dict
