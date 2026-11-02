class QuimiaIngestionError(Exception):
    """Erro base do serviço."""


class ConfigurationError(QuimiaIngestionError):
    pass


class ContractError(QuimiaIngestionError):
    pass


class ExternalServiceError(QuimiaIngestionError):
    pass


class ExtractorHTTPError(ExternalServiceError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(f"extractor retornou HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class ImageRejectedError(QuimiaIngestionError):
    pass
