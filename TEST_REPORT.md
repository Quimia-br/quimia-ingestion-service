# Test Report

Atualizado em 2026-11-01 (v0.2.x, após as correções de estabilização P0 §2–§5 e P1 §6–§8).

## 1. Testes automatizados (pytest)

```text
%USERPROFILE%\.venvs\quimia-ingestion\Scripts\python -m pytest -q
121 passed   (tests/unit: 95, tests/integration: 26)
```

Todos usam mocks/fixtures: nenhum acessa Aiven, GitHub, ZenRows ou o extractor real.
Histórico: 37 testes na v0.2.0; 58 ao fim da sessão de 2026-10-31; 121 agora.

Cobertura:

- guard de banco local (localhost/127.0.0.1/::1 permitidos; Aiven, hosts remotos, ausente, `DATABASE_URL`, `PGHOSTADDR`, `PGSERVICE` bloqueados; nenhum comando de escrita conecta com destino remoto);
- precedência do ambiente sobre o `.env`; `safety-check` local e remoto;
- extractor: seção 03/04 ausente ou vazia vai para revisão sem escrita; HTTP 400/502 não persistem nem repetem; cache por hash; falha de banco não paga duas vezes; seção 10 ausente persiste com pendência;
- imagens: quality gate (fundo, moldura, halo, franja, produto branco/cortado/pequeno, JPEG renomeado, canvas), idempotência (2ª rodada sem busca/download/rembg), reconciliação de falha parcial, estado perdido, PNG corrompido, colisão de `product_id`;
- matcher: marca por frase, outra marca (Downy/Urca/Comfort), kits, multiplicador `24x`, alias, variante;
- consistência de configuração (canvas 1254, limiares de produção, uma única variável de canvas);
- sessão única do `rembg`;
- providers de FDS e ZenRows (retry em 429/5xx, 401/402 sem retry), validador de PDF, manual inbox, publisher local, ausência de git remote.

## 2. Testes com serviços reais (manuais, fora do pytest)

Feitos em 2026-10-31/11-01, sempre em ambiente local; nenhuma escrita na Aiven ou no GitHub.

- ZenRows (Bing Images, DuckDuckGo, fallback), com créditos reais (custo desprezível);
- `discover-public` contra Flora e Unilever (23 FDS aceitas);
- extractor real em 29 das 47 FDS (cache): 16 HTTP 200 (7 completos), 9 HTTP 502, 4 HTTP 400;
- PostgreSQL local (Docker `quimia-pg-test`): schema do `quimia-bd`, trigger, deduplicação por hash;
- Ingestão completa no PostgreSQL local (`quimia-pg-test`, 2026-11-01), código final, validação de seções e cache ativos, reproduzindo as 29 respostas reais do extractor gravadas (nenhuma chamada nova ao LLM), marca de teste `TESTE-ESTAB`, validador de PDF desligado (a marca de teste não consta nos PDFs):
  - rodada 1: 7 gravadas (+7 FDS, +21 compostos, +28 primeiros socorros, +23 incompatibilidades, materializados pelo trigger); 22 em `REVIEW_REQUIRED` (9 HTTP 502, 4 HTTP 400, 9 com seção 03/04 ausente ou vazia), sem nenhuma linha no banco; 1 duplicata por hash;
  - rodada 2 (mesmo `state.db`): 0 chamadas ao extractor e 0 linhas novas em todas as tabelas;
  - na rodada anterior, a FDS Minuano Neutro (já gravada por outro caminho) foi reconhecida como `DUPLICATE` por `fonte_url`, com o validador ligado e marcas reais;
- Extractor real em 10 das 23 FDS descobertas (2026-11-01; ~45 s por PDF, custo de LLM real), pelo workflow real, com repositório que só registra (nenhum banco escrito). Escolha: 5 com melhor nome/versão/score de imagem e 5 com nome-lixo ou imagem fraca. Resultado: 3 gravariam (#2 Brisa Maçã, #18 Brisa "BR Esta informação…", #11 OMO Desinfetante), 5 HTTP 502, 2 HTTP 504 (timeout do extractor, ~57 s; ficam `FAILED` e não são cacheados). O score não previu o sucesso (boas: 1 de 5; fracas: 2 de 5). Respostas guardadas em `%TEMP%\qi-run\run_ext10`;
- Nome do produto pelo cabeçalho do PDF (sem LLM): recuperou os 10 nomes-lixo dos 23 descobertos e 10 de 47 FDS da pasta `Materiais` (as da Flora); 0 falsos positivos. O rótulo genérico "Nome do produto" foi testado e descartado (devolvia "Código", "CAS/CE…");
- `rembg` real (u2net) em 12 fotos; saída idêntica pixel a pixel com sessão compartilhada;
- 2ª rodada de imagens sobre cópia do `quimia-bd`: `ALREADY_PUBLISHED`, 0 buscas/downloads/rembg, nenhum arquivo alterado (listagem de produtos fixa, pois o Docker estava parado).

## 3. Interrompidos / não reproduzidos

- O teste do extractor parou em 29 de 47 para poupar tokens do LLM.
- A queda `0xC0000409` do `rembg` não foi reproduzida em mais de 20 chamadas isoladas.

## 4. Pendentes

- Ingestão no PostgreSQL local com o extractor real e as 23 FDS descobertas (nunca foram enviadas ao extractor; só as 29 da pasta `Materiais` têm resposta em cache). O container mantém as linhas `TESTE-CONTRATO` e `TESTE-ESTAB`;
- 1ª rodada de imagens com serviços reais depois do estado persistente (exigiria limiar reduzido; coberta por testes automatizados);
- Mr. Músculo: sem fonte automática (scjohnson.com.br inacessível, scjohnson.com e mrmuscleclean.com sem FDS); usa a manual inbox;
- 18 FDS restantes no extractor; as correções de `SECÇÃO`/502 dependem do mantenedor do `quimia-extractor-ai` (ver `NOTA_EXTRATOR_AI.md`);
- PubChem.
