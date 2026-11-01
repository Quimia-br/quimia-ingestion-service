from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS document_state (
                    pdf_sha256 TEXT PRIMARY KEY,
                    source_id TEXT,
                    source_url TEXT,
                    brand TEXT NOT NULL,
                    product_name TEXT NOT NULL,
                    version TEXT,
                    update_date TEXT,
                    status TEXT NOT NULL,
                    fds_id INTEGER,
                    pdf_path TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS ix_document_state_source ON document_state(source_url)")
            # Chave = marca|produto (casefold), não o id: o id muda entre bancos (local x Aiven).
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_state (
                    product_key TEXT PRIMARY KEY,
                    product_id INTEGER,
                    asset_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    published_at TEXT NOT NULL
                )
                """
            )

    def get_by_hash(self, digest: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM document_state WHERE pdf_sha256 = ?", (digest,)).fetchone()
            return dict(row) if row else None

    def upsert(
        self,
        *,
        digest: str,
        source_id: str,
        source_url: str,
        brand: str,
        product_name: str,
        version: str | None,
        update_date: str | None,
        status: str,
        fds_id: int | None = None,
        pdf_path: str | None = None,
        last_error: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO document_state (
                    pdf_sha256, source_id, source_url, brand, product_name, version, update_date,
                    status, fds_id, pdf_path, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(pdf_sha256) DO UPDATE SET
                    source_id=excluded.source_id,
                    source_url=excluded.source_url,
                    brand=excluded.brand,
                    product_name=excluded.product_name,
                    version=excluded.version,
                    update_date=excluded.update_date,
                    status=excluded.status,
                    fds_id=COALESCE(excluded.fds_id, document_state.fds_id),
                    pdf_path=COALESCE(excluded.pdf_path, document_state.pdf_path),
                    last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (digest, source_id, source_url, brand, product_name, version, update_date, status,
                 fds_id, pdf_path, last_error, now, now),
            )

    def get_image(self, product_key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM image_state WHERE product_key = ?", (product_key,)).fetchone()
            return dict(row) if row else None

    def set_image(self, product_key: str, product_id: int | None, asset_path: str, sha256: str, status: str = "PUBLISHED") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO image_state (product_key, product_id, asset_path, sha256, status, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_key) DO UPDATE SET product_id=excluded.product_id, asset_path=excluded.asset_path,
                    sha256=excluded.sha256, status=excluded.status, published_at=excluded.published_at
                """,
                (product_key, product_id, asset_path, sha256, status, datetime.now(timezone.utc).isoformat()),
            )

    def summary(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS total FROM document_state GROUP BY status").fetchall()
            return {row["status"]: row["total"] for row in rows}
