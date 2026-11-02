from __future__ import annotations

import hashlib
from pathlib import Path


class DocumentStorage:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def save_pdf(self, content: bytes, digest: str | None = None) -> Path:
        digest = digest or self.sha256(content)
        path = self.root / "fds" / digest[:2] / f"{digest}.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(content)
        return path
