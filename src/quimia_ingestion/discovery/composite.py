from __future__ import annotations


class CompositeSDSProvider:
    """Combina providers sem repetir a mesma URL/documento.

    Uma fonte indisponível não derruba as demais; erros ficam registrados em `errors`.
    """

    def __init__(self, providers):
        self.providers = list(providers)
        self.errors: list[dict[str, str]] = []

    def documents(self):
        seen_urls: set[str] = set()
        seen_content: set[bytes] = set()
        for provider in self.providers:
            try:
                iterator = provider.documents()
                for document in iterator:
                    if document.source_url in seen_urls:
                        continue
                    signature = document.content[:128] + str(len(document.content)).encode()
                    if signature in seen_content:
                        continue
                    seen_urls.add(document.source_url)
                    seen_content.add(signature)
                    yield document
            except Exception as exc:
                self.errors.append({"provider": provider.__class__.__name__, "error": str(exc)})
                continue
