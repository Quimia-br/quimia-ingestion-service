from quimia_ingestion.domain.models import SDSDocument, PDFValidationReport
from quimia_ingestion.workflows.discover_fds import PublicDiscoveryExportWorkflow


class Provider:
    def documents(self):
        yield SDSDocument("1", "https://official/x.pdf", "OMO", "OMO Produto", b"%PDF" + b"x" * 600, provider="unilever", source_score=100)
        yield SDSDocument("2", "https://secondary/y.pdf", "OMO", "OMO Outro", b"%PDF" + b"y" * 600, provider="search", source_score=70)


class Validator:
    def validate(self, *args, **kwargs):
        return PDFValidationReport(True)


def test_discovery_export_only_manifests_auto_approved(tmp_path):
    result = PublicDiscoveryExportWorkflow(provider=Provider(), output_dir=tmp_path, validator=Validator(), min_auto_source_score=85).run()
    assert result["accepted"] == 1
    assert result["review_required"] == 1
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "review_required.json").exists()
