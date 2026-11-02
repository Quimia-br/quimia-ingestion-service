# Changelog

## 0.2.1 (estabilização, 2026-11-01)

- Guard de banco: escrita só em PostgreSQL local (localhost/127.0.0.1/::1), bloqueando também `DATABASE_URL`/`PGHOSTADDR`/`PGSERVICE`; `safety-check` mostra o destino e falha se remoto.
- FDS: seções 03/04 ausentes ou vazias vão para revisão sem tocar no banco; cache da resposta do extractor por hash; HTTP 400/502 não são repetidos.
- Imagens: estado persistente (`image_state`) e verificação PNG+seed+manifest; a 2ª rodada não busca nem processa; gravação atômica; manifest mesclado por marca+produto.
- `rembg`: sessão única (de ~52 s para ~0,8 s por imagem); `scripts/smoke_rembg.py`.
- Matcher: marca por frase/alias, rejeição de outras marcas (`other_brands`), kits, nome de busca sem `24x`.
- Nome do produto: busca web lê o nome do cabeçalho do PDF (formato Flora) em vez do título do resultado.
- Fontes: provider SC Johnson removido da cadeia (site `.com.br` inacessível; sem FDS no site ativo); Mr. Músculo via manual inbox. A validação estrutural do PDF agora é sempre aplicada, também em `ingest-local`/`run-all-local`.

## 0.2.0

- BridgeSDS deixou de ser dependência obrigatória.
- Adicionado `ConfiguredOfficialSDSProvider`.
- Adicionado catálogo público da Unilever para OMO.
- Adicionados crawlers por sitemap para Flora e SC Johnson.
- Adicionado fallback de FDS via SerpApi.
- Adicionado `ManualInboxProvider` com sidecar JSON opcional.
- Adicionado `CompositeSDSProvider` resiliente a falha individual de fonte.
- Adicionado `SDSStructuralValidator` com validação das seções 03/04/10.
- Extração de versão/data documental para melhorar idempotência.
- Fontes secundárias abaixo do score automático viram `REVIEW_REQUIRED`.
- Novo `discover-public`, que não toca no banco.
- `ingest-public` exige `--write-db` explicitamente.
- Stub de PubChem para integração futura pós-seção 3.
- Mantida política local-only para Git/GitHub.
