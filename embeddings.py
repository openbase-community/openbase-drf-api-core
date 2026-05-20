from typing import NamedTuple

import structlog

logger = structlog.get_logger(__name__)


class EmbeddingsModel(NamedTuple):
    name: str
    dimensions: int


OPENAI_TEXT_EMBEDDING_3_LARGE = EmbeddingsModel(
    name="text-embedding-3-large",
    dimensions=3072,
)
