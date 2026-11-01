# quimia-ingestion-service — v0.2 local

Serviço independente do Quimia para automatizar:

1. descoberta e ingestão de FDS públicas;
2. extração das seções 03/04/10 via `quimia-extractor-ai`;
3. persistência no PostgreSQL atual, sem migration obrigatória;
4. busca/processamento de imagens de produto;
5. atualização de assets/seed/manifest em um checkout **local** do `quimia-bd`.

## Segurança desta versão

**LOCAL ONLY para Git.** Não existe código de `git push`, criação de PR ou escrita via API do GitHub. `LocalBdPublisher` só altera o caminho local passado explicitamente.

**Escrita no banco só em PostgreSQL local.** O `PostgresQuimiaRepository` recusa, no construtor e antes de qualquer conexão, destino que não seja `localhost`, `127.0.0.1` ou `::1` (host vazio ou desconhecido também é bloqueado). Também bloqueia `DATABASE_URL`, `PGHOSTADDR` e `PGSERVICE` definidos no ambiente, que poderiam desviar a conexão. Vale para todos os comandos e workflows (`ingest-local`, `ingest-public`, `enrich-images`, `run-all-local`) e não há bypass. O `.env` aponta para a Aiven: para escrever, sobrescreva as variáveis `QUIMIA_DB_*` com o banco local (ex.: `QUIMIA_DB_HOST=localhost QUIMIA_DB_PORT=55432`). `safety-check` mostra o destino efetivo (sem credenciais) e sai com código 1 se for remoto.

`ingest-public` ainda exige `--write-db`. Para testar descoberta sem tocar no banco, use `discover-public`.

## Marcas v0.2

- Minuano
- Assim
- Brisa
- OMO
- Mr. Músculo

Flora é fabricante auxiliar de Minuano/Assim/Brisa e não é gravada como marca do produto.

## Nova estratégia de descoberta de FDS

BridgeSDS não é mais dependência da arquitetura. Os providers são combinados nesta ordem:

```text
ConfiguredOfficialSDSProvider
        ↓
UnileverSDSProvider
        ↓
FloraSDSProvider (sitemap/crawl)
        ↓
WebSearchSDSProvider (DuckDuckGo HTML via ZenRows, fallback opcional)
        ↓
ManualInboxProvider
```

`CompositeSDSProvider` deduplica URLs/documentos e continua mesmo se um provider estiver indisponível.

### Estado real por fonte (verificado em 2026-11-01)

| Marca | Fonte | Situação |
|---|---|---|
| Minuano, Assim, Brisa | Flora (sitemap/crawl) | Funcional: 14 FDS descobertas em teste real |
| OMO | Catálogo Unilever Professional | Funcional: 9 FDS descobertas em teste real |
| Mr. Músculo | — | **Descoberta automática não operacional.** Use a manual inbox |

Sobre o SC Johnson: `scjohnson.com.br` resolve DNS mas nunca completa a conexão TCP (timeout direto, e o ZenRows também estoura o tempo), então o timeout anterior não era bloqueio e o ZenRows não resolve. O site ativo (`scjohnson.com/pt-br`) e o `mrmuscleclean.com` não publicam FDS no sitemap nem em links. Por isso o provider foi removido da cadeia padrão. Se aparecer uma URL oficial de FDS do Mr. Músculo, ela pode entrar em `config/official_sds_catalog.yaml`.

**Nome do produto.** Resultados da busca web trazem como "título" um trecho qualquer do PDF (ex.: "Brisa BR Esta informação está baseada em nosso conhecimento…"). Por isso `WebSearchSDSProvider` lê o nome do cabeçalho do PDF (`product_name_from_pdf`: "Versão: NN NOME PT (português…)", formato das FDS da Flora; 23 de 23 nos PDFs da Flora testados) e só cai no título do resultado se o cabeçalho não tiver esse padrão. O nome vem em caixa alta e abreviado como na FDS ("DET. PO ASSIM TRIPLACAO"): serve para identificar o produto, mas pode precisar de curadoria antes de ir ao `quimia-bd`. FDS de outros fabricantes (ex.: OMO) não têm esse cabeçalho e usam o nome da fonte (catálogo).

Nenhuma fonte aprova um PDF só pelo score: mesmo com domínio oficial (score 90–100), todo PDF passa pela validação estrutural (FDS, seções 03/04/10, marca e produto) antes do extractor, inclusive em `ingest-local` e `run-all-local`. O flag `--validate-pdf` ficou sem efeito (a validação é sempre aplicada).

### Fontes oficiais

`config/official_sds_catalog.yaml` contém um pequeno bootstrap de URLs oficiais já conhecidas. Ele não pretende ser catálogo completo. O crawler tenta descobrir outras FDS pelos sitemaps/páginas públicas dos fabricantes.

Para OMO, o serviço usa o catálogo público de FDS da Unilever Professional.

### Busca fallback

Todos os providers tentam HTTP direto primeiro. Só quando o site responde 403/429/503, página de Cloudflare/captcha/"enable JavaScript" ou timeout, a mesma URL é buscada via ZenRows (`mode=auto`, que só cobra a configuração que funcionou).

Se `ZENROWS_API_KEY` estiver vazia, não há fallback nem busca web: as fontes oficiais (HTTP direto) e a pasta manual continuam funcionando. `enrich-images` exige a chave (Bing Images via ZenRows).

Resultados de busca recebem score de confiança:

- domínio oficial: 90;
- fonte externa: 70;
- limiar automático padrão: 85.

Portanto uma fonte externa não entra diretamente no extractor/banco: vira `REVIEW_REQUIRED`.

### Manual inbox

Coloque PDFs em:

```text
data/manual_inbox/
```

Exemplo:

```text
FDS_Minuano_Limpador_Multiuso.pdf
```

O serviço tenta inferir marca/produto pelo filename. Para controlar os metadados, crie um sidecar:

```text
FDS_Minuano_Limpador_Multiuso.pdf.json
```

```json
{
  "brand": "Minuano",
  "product_name": "Limpador Multiuso",
  "version": "2",
  "data_atualizacao": "2026-08-14"
}
```

## Validação de FDS

Antes do extractor, `SDSStructuralValidator` verifica:

- assinatura PDF;
- PDF legível;
- identificação como FDS/FISPQ;
- presença das seções 03, 04 e 10;
- correspondência de marca/produto;
- versão e data documental quando disponíveis.

Mismatch de marca/produto pode gerar revisão; documento que não parece FDS ou não possui as seções obrigatórias é rejeitado.

## Fluxo recomendado: primeiro descobrir, depois ingerir

### 1. Descoberta sem banco

```bash
python -m quimia_ingestion.cli discover-public
```

Gera localmente:

```text
data/discovered/
├── manifest.json
├── review_required.json
├── rejected.json
└── pdfs/
```

### 2. Ingestão do manifest revisado

```bash
python -m quimia_ingestion.cli ingest-local data/discovered/manifest.json --validate-pdf
```

### Ingestão pública direta

Existe, mas exige confirmação explícita:

```bash
python -m quimia_ingestion.cli ingest-public --write-db
```

## Idempotência sem alterar `fds`

Não é necessária migration na v0.2.

`state.db` mantém:

- SHA-256 do PDF;
- URL de origem;
- caminho local;
- status operacional;
- `fds_id` quando persistido.

O banco mantém a segunda barreira por `fonte_url` e, quando existirem metadados suficientes, por produto + versão/data. Se versão **e** data forem desconhecidas, o serviço não assume duplicidade somente porque o produto é o mesmo.

## Extractor

Contrato usado:

- `POST /extracoes`;
- multipart `arquivo`;
- Bearer token;
- retorno com `secoes.03`, `secoes.04`, `secoes.10` e `pendencias`.

O serviço não interpreta química nem inventa pendências. Ele persiste `raw_json`; a lógica química continua fora dele.

HTTP 200 com schema válido não basta. As seções **03** (`compostos`) e **04** (`primeiros_socorros`) precisam existir (`encontrada: true`) **e** ter conteúdo; caso contrário a FDS vai para `REVIEW_REQUIRED`, sem criar produto nem gravar no banco. A seção 10 ausente continua sendo gravada com pendência.

Cada resposta paga é salva ao lado do PDF (`<hash>.extraction.json`) e reutilizada: o mesmo PDF não é reenviado ao extractor, nem depois de falha no banco. HTTP 400 e 502 também não são repetidos (`<hash>.extraction_error.json` + `REVIEW_REQUIRED`); outros erros (401, timeout) continuam repetíveis. Para forçar nova extração de um PDF, apague sua linha no `state.db` e o `.json` correspondente.

## PubChem

Existe apenas o stub `PubChemEnricher`. A integração futura deve ocorrer **depois** da extração da seção 3, usando CAS/nome de substância. PubChem não participa da descoberta de FDS por produto.

## Imagens

Fluxo mantido:

```text
busca → download → rembg → normalização → PNG RGBA → quality gate → publisher local
```

**Idempotência.** Um produto só é considerado publicado se o PNG, o hash no manifest e a linha do `seed_produto.csv` forem consistentes; nesse caso a rodada seguinte não busca, não baixa e não roda `rembg` (resultado `ALREADY_PUBLISHED`). O registro fica no `state.db` (`image_state`: chave marca|produto, caminho, SHA-256, status, data) e é reconstruído dos arquivos se for perdido. A gravação é atômica na ordem PNG, seed, manifest; uma queda no meio é reconciliada na rodada seguinte sem duplicar arquivo, linha ou entrada. O `foto_url` do banco não é atualizado pelo serviço (a URL só existe após o push do `quimia-bd`; ela chega pelo seed). Produtos em `REVIEW_REQUIRED` continuam sendo buscados a cada rodada.

**Fontes.** `enrich-images` consulta primeiro a **loja oficial da Flora** (`compraflora.com.br`, Nuvemshop; `integrations/flora_store.py`) para Minuano, Assim e Brisa: lê o sitemap, escolhe os produtos com mais palavras em comum com a busca e usa o `og:title`/`og:image` de cada página (foto ampliada para 1024 px). Depois entra o Bing Images via ZenRows. O domínio da loja fica em `image_domains` (não em `official_domains`, que também dirige a busca de FDS). Sem domínio oficial o score máximo é 0,88, abaixo do limiar de 0,90, então **só a loja oficial publica sem revisão**; OMO e Mr. Músculo não têm fonte oficial de imagem e sempre caem em revisão.

**Matching.** Marca por frase inteira (com aliases); candidato que cite marca de outro fabricante (`other_brands` em `config/brands.yaml`, ex.: "Downy Brisa Suave") é rejeitado; kits perdem 0,35; nome ou variante incompletos ficam limitados a 0,69 (nunca auto-aprovados). A busca usa o nome sem multiplicador de caixa ("24x500mL" vira "500mL"); o nome original é preservado.

**rembg.** Usa uma única sessão do modelo por execução (antes cada imagem recarregava o modelo: ~52 s contra ~0,8 s). Diagnóstico do crash `0xC0000409` (não reproduzido): `python scripts/smoke_rembg.py --runs 5 --calls 6`.

Canvas padrão: **1254×1254** (`IMAGE_CANVAS_SIZE`, igual aos PNGs já existentes no `quimia-bd`). Limiares de produção: `IMAGE_AUTO_APPROVE_SCORE=0.90`, `IMAGE_REVIEW_SCORE=0.70`.

O quality gate reprova, entre outros:

- PNG sem transparência real;
- fundo branco/colorido;
- borda/franja externa visível;
- resolução baixa;
- canvas inválido.

Instalação com processamento de imagem:

```bash
pip install ".[images]"
```

PostgreSQL:

```bash
pip install ".[postgres]"
```

Tudo + testes:

```bash
pip install ".[all]"
```

No Windows, crie a venv **fora do OneDrive**: o caminho longo do projeto estoura o limite de 260 caracteres ao instalar o `onnxruntime` (dependência do rembg).

```bash
py -3.14 -m venv %USERPROFILE%\.venvs\quimia-ingestion
%USERPROFILE%\.venvs\quimia-ingestion\Scripts\python -m pip install -e ".[all]"
```

O `.env` na raiz do projeto é carregado automaticamente (variáveis já definidas no ambiente têm prioridade).

## Comandos úteis

```bash
python -m quimia_ingestion.cli safety-check
python -m quimia_ingestion.cli bridge-status
python -m quimia_ingestion.cli discover-public
python -m quimia_ingestion.cli ingest-local data/discovered/manifest.json --validate-pdf
python -m quimia_ingestion.cli enrich-images --bd-repo /caminho/local/quimia-bd
python -m quimia_ingestion.cli status
```

## Testes

```bash
pytest -q
```

Os testes automatizados (134: 107 unitários e 27 de integração) não acessam Aiven, GitHub, ZenRows ou o extractor real: HTTP, banco e `rembg` são mockados. Testes contra serviços reais são manuais, em ambiente local, e ficam registrados em `TEST_REPORT.md` e `SESSAO_2026-10-31.md`.
