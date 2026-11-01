# Relatório — Frente 2: imagens

Data: 2026-11-01. Repositório alterado: `quimia-ingestion-service`. Nada commitado. Sem escrita na Aiven, no `quimia-bd` real ou no GitHub.

Written for: o time do Quimia.

## 1. Resumo

| Item | Situação | Resultado |
|---|---|---|
| Publicação realmente nova | **Validada** | Produto ausente do `quimia-bd`: PNG, seed e manifest criados |
| Segunda execução | **Validada** | 0 downloads, 0 `rembg`, nenhum arquivo alterado (hash e data) |
| Qualidade do matching | **1 bug corrigido, 1 limite estrutural encontrado** | Ver seções 3 e 4 |

**Limiar:** a publicação foi feita com `auto_approve_score=0.75`, só no script de teste e só sobre uma cópia limpa (`%TEMP%\qi-run\bd_new`). O limiar de produção (0,90) não foi alterado. Com 0,90, nada teria sido publicado (seção 4).

## 2. Publicação nova e segunda execução

Setup: Postgres local (`quimia-pg-test`), cópia do `quimia-bd` só com o seed original, `state.db` novo. Busca real no ZenRows.

| | Rodada 1 | Rodada 2 |
|---|---|---|
| Produto 1 (Minuano Detergente Neutro, novo na cópia) | `PUBLISHED_LOCAL`, score 0,77 | `ALREADY_PUBLISHED` |
| Buscas | 4 | 3 (só os 3 produtos sem imagem) |
| Downloads | 4 | **0** |
| `rembg` | 4 | **0** |
| Arquivos alterados | PNG, seed, manifest | **nenhum** |

PNG publicado: 1254×1254, RGBA, transparência real. Manifest com fonte, score e hash. Seed com uma linha nova.

Os outros produtos de teste (amaciante, detergente em pó Minuano e Assim) ficaram em revisão. Os dois candidatos do amaciante foram barrados pelo gate de qualidade (fundo/borda), que é o comportamento esperado.

## 3. Bug encontrado: a imagem publicada era ruim

O PNG passou no gate técnico, mas mostra uma **caixa de papelão com marca d'água "DNAC"** ao lado do frasco. O candidato tinha título `24un Detergente Lava Loucas Neutro 500ml Minuano - DNAC`.

- **Causa:** o padrão de kit exigia espaço entre número e unidade (`24 un`). `24un` colado passava como unidade avulsa.
- **Correção:** `src/quimia_ingestion/images/matcher.py`, espaço opcional. Esse candidato cai de **0,77 para 0,50**.
- **Teste:** `tests/unit/test_matcher.py` cobre `24un` e `12und`.
- O gate de qualidade não enxerga conteúdo (caixa, marca d'água, outro produto). Só o texto do candidato protege contra isso.

## 4. Limite estrutural do matching

- **Sem domínio oficial, o score máximo é 0,88** (0,30 marca + 0,40 produto + 0,08 produto + 0,07 tamanho + 0,03 PNG). O limiar é 0,90. **Só imagem de site oficial é publicada automaticamente.**
- Nos 3 produtos testados, a melhor imagem de varejo foi 0,77. A busca `site:flora.com.br` no Bing Images devolve 0 resultados. Então, na prática, a publicação automática hoje é zero.
- Tamanho errado já cai em revisão (ex.: 1,8 kg e 400 g para um produto de 900 g, teto 0,69).
- Não existe fila de revisão: os `REVIEW_REQUIRED` só ficam no retorno do comando.

## 5. Outras mudanças

- `REVIEW_REQUIRED` agora traz `candidates`. Na rodada 1, um produto voltou com score 0,0 e na rodada 2 com 0,69: foi uma busca que veio vazia sem aviso. `candidates: 0` identifica esse caso. Teste: `test_empty_search_is_reported_as_zero_candidates_not_just_low_score`.
- A busca varia entre rodadas (o amaciante deu 0,77 e depois 0,70). Não é cacheada.

Testes: 121 → **122 passando**, 0 falhas.

## 6. Decisões e próximos passos

1. **Fonte oficial direta.** O site `flora.com.br` tem listagem de produtos (`/produtos`). Um provider que pegue a imagem de lá permitiria chegar a 0,90 legitimamente para Minuano, Assim e Brisa. É uma feature nova; não foi feita.
2. **Fila de revisão.** Salvar os 3 a 5 melhores candidatos (URL, score, motivo) de cada `REVIEW_REQUIRED`, para uma pessoa aprovar. Sem isso, todo produto de varejo fica parado.
3. **Limiar.** Se o time aceitar publicar imagem de varejo sem revisão humana, o limiar teria que mudar. Eu não recomendo: o caso da seção 3 mostra o risco.
4. **Não testado:** o crash `0xC0000409` do `rembg` não apareceu nas 8 chamadas desta sessão. Python 3.12 continua sem teste.
5. Cache da busca de imagens por produto, para não gastar ZenRows em cada rodada (hoje ~0,001 crédito por busca; foram 14 nesta frente).
