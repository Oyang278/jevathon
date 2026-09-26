"""Contract between the fetch/batch pipeline and the processing stage."""

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image

REVIEW_ALBUM = "Jev: needs review"
DELETE_ALBUM = "Jev: proposed deletions"


@dataclass
class PhotoRef:
    id: str
    label: str
    thumb: str


@dataclass
class FetchedPhoto:
    ref: PhotoRef
    image: Image.Image


@dataclass
class Decision:
    id: str
    actions: list[str]
    answers: dict
    state: dict
    latency_ms: float
    phash: str
    sharpness: float
    extra: dict = field(default_factory=dict)


class Processor(Protocol):
    def prime(self, prior: list[dict]) -> None:
        """Receive records from earlier runs (results.jsonl lines) for cross-batch dedupe."""

    async def process(self, batch: list[FetchedPhoto]) -> list[Decision]:
        """Classify one in-memory batch. Must not retain the images after returning."""

    def summary(self) -> str:
        """One-line running stats (calls, cost) for the batch progress line."""

    async def close(self) -> None: ...
