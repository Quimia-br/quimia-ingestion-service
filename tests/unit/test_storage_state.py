from quimia_ingestion.storage.documents import DocumentStorage
from quimia_ingestion.state.sqlite import StateStore


def test_document_storage_hash_and_save(tmp_path):
    storage = DocumentStorage(tmp_path / "docs")
    content = b"%PDF-1.4 test"
    digest = storage.sha256(content)
    path = storage.save_pdf(content, digest)
    assert len(digest) == 64
    assert path.exists()
    assert path.read_bytes() == content
    assert digest in path.name


def test_state_upsert_and_lookup(tmp_path):
    state = StateStore(tmp_path / "state.db")
    state.upsert(
        digest="a" * 64,
        source_id="x",
        source_url="https://example.test/fds.pdf",
        brand="Minuano",
        product_name="Multiuso",
        version="1",
        update_date="2026-01-01",
        status="PERSISTED",
        fds_id=10,
        pdf_path="/tmp/a.pdf",
    )
    row = state.get_by_hash("a" * 64)
    assert row["status"] == "PERSISTED"
    assert row["fds_id"] == 10
