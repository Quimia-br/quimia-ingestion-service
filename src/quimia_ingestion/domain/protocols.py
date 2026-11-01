from __future__ import annotations

from pathlib import Path
from typing import Protocol, Iterable

from .models import SDSDocument, ExtractorResponse, ProductRecord, ImageCandidate


class SDSProvider(Protocol):
    def documents(self) -> Iterable[SDSDocument]: ...


class ExtractorClient(Protocol):
    def extract(self, pdf: bytes, filename: str = "fds.pdf") -> ExtractorResponse: ...


class QuimiaRepository(Protocol):
    def find_fds_by_source_url(self, source_url: str) -> int | None: ...
    def find_fds_by_identity(self, product_id: int, version: str | None, update_date) -> int | None: ...
    def get_or_create_product(self, brand: str, product_name: str) -> int: ...
    def insert_fds(self, product_id: int, version: str | None, update_date, source_url: str, raw_json: dict) -> int: ...
    def list_products_without_image(self) -> list[ProductRecord]: ...


class ImageSearchProvider(Protocol):
    def search(self, query: str) -> list[ImageCandidate]: ...


class BackgroundRemover(Protocol):
    def remove(self, image_bytes: bytes) -> bytes: ...


class ArtifactPublisher(Protocol):
    def publish_product_image(self, product: ProductRecord, png_bytes: bytes, source: ImageCandidate, score: float) -> Path: ...
