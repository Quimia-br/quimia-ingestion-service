# Arquitetura — quimia-ingestion-service v0.2

## Fronteiras

O serviço é independente de:

- `quimia-bd`: integração somente via PostgreSQL e um publisher para checkout local;
- `quimia-extractor-ai`: integração HTTP;
- providers de FDS: adapters independentes;
- providers de imagem: adapters independentes.

Nenhum módulo do `quimia-bd` ou do extractor é importado diretamente.

## Descoberta

```text
                  ┌─ catálogo oficial configurado
                  ├─ catálogo Unilever
SDS Discovery ────┼─ sitemap/crawl Flora
                  ├─ sitemap/crawl SC Johnson
                  ├─ busca web fallback (opcional)
                  └─ manual inbox
                            ↓
                    CompositeSDSProvider
                            ↓
                   SDSStructuralValidator
                            ↓
             accepted / review / rejected
```

### Confiança

- oficial configurado: 100;
- catálogo/crawler oficial: 100;
- busca apontando para domínio oficial: 90;
- busca em domínio externo: 70;
- manual inbox: 95.

`FDS_MIN_AUTO_SOURCE_SCORE=85` por padrão.

## Ingestão

```text
SDSDocument
   ↓
SHA-256 / state.db
   ↓
allowlist de marca
   ↓
validação estrutural
   ↓
fonte confiável?
   ├─ não → REVIEW_REQUIRED
   └─ sim
        ↓
fonte_url já existe?
        ↓
extractor HTTP
        ↓
get/create marca e produto
        ↓
produto + versão/data já existe?
        ↓
INSERT fds(raw_json)
```

Versão/data são obtidas do provider quando disponíveis e, caso contrário, tentadas a partir do texto da FDS.

## Deduplicação

1. hash no `state.db`;
2. `fds.fonte_url`;
3. produto + versão/data quando ao menos um dos metadados existe.

Não existe deduplicação somente por produto quando versão e data são ambas desconhecidas.

## Estado

SQLite continua sendo estado operacional, não fonte química de verdade.

Estados principais:

```text
PERSISTED
DUPLICATE
REVIEW_REQUIRED
REJECTED
FAILED
```

## Imagens

Sem alteração de arquitetura na v0.2:

```text
produto sem foto
  ↓
busca
  ↓
ranking
  ↓
download
  ↓
rembg
  ↓
normalize
  ↓
quality gate
  ↓
LocalBdPublisher
```

Nenhuma escrita remota Git está implementada.

## PubChem futuro

PubChem deve ser um enricher de substâncias depois da seção 3:

```text
extractor → CAS/nome → PubChem → enriquecimento/validação
```

Ele não deve se tornar provider de FDS por produto.
