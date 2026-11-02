# Relatório final — estabilização do Quimia Ingestion Service

Data: 2026-11-01. Escopo: `PLANO_CORRECOES_ESTABILIZACAO_QUIMIA.md`, seções 2 a 8 (P0 e P1).

Written for: o time do Quimia e quem mantém o `quimia-extractor-ai` (a seção 3 traz pendências que dependem dele).

## 1. Resumo das correções

**Estado:** funciona de ponta a ponta para uso local controlado. **Não está pronto para produção.** O principal limite é o extractor: só cerca de 30% das FDS testadas passam sem revisão manual.

| Seção do plano | Situação | O que foi feito |
|---|---|---|
| §2 Guard contra escrita na Aiven | Concluída | Escrita só em `localhost`, `127.0.0.1` e `::1`. Bloqueia também `DATABASE_URL`, `PGHOSTADDR` e `PGSERVICE`. `safety-check` mostra o destino e sai com código 1 se for remoto. |
| §3 Validação do extractor | Concluída no ingestion | Seções 03 e 04 precisam existir e ter conteúdo, senão a FDS vai para revisão sem tocar no banco. Respostas são cacheadas por hash. HTTP 400 e 502 não são repetidos. |
| §3 Extractor (`SECÇÃO`, 502) | Pendente no extractor | Não alterado, por decisão. Nota técnica em `NOTA_EXTRATOR_AI.md`. |
| §4 Idempotência de imagens | Concluída | Estado em `image_state`, verificação PNG + seed + manifest, gravação atômica. A segunda rodada não busca, não baixa e não roda `rembg`. |
| §5 Crash `rembg` (`0xC0000409`) | Não reproduzido | Diagnóstico com `scripts/smoke_rembg.py`: mais de 20 chamadas isoladas sem falha. Corrigido o recarregamento do modelo a cada imagem (de ~52 s para ~0,8 s). Causa não confirmada. |
| §6 Matching de imagens | Concluída | Marca por frase e alias. Outras marcas (ex.: "Downy Brisa Suave") são rejeitadas. Kits perdem score. Nome sem multiplicador `24x` na busca. Threshold de produção intacto. |
| §7 Canvas, config e docs | Concluída | `IMAGE_CANVAS_SIZE=1254` em todos os lugares. Documentação e contagens de testes atualizadas. |
| §8 Fontes de FDS | Concluída, com limitação | SC Johnson removido da cadeia (site inacessível). Mr. Músculo só pela manual inbox. Validação do PDF sempre aplicada. |

**Extras feitos durante a sessão:**
- Nome do produto lido do cabeçalho do PDF (formato Flora), com 0 falsos positivos nos PDFs testados.
- Ingestão completa no Postgres local, incluindo deduplicação na segunda rodada.

## 2. Arquivos alterados

Nada foi commitado. O repositório ainda não tem nenhum commit.

Código:
- `src/quimia_ingestion/integrations/postgres.py` (guard)
- `src/quimia_ingestion/cli.py` (safety-check, bloqueio de comandos, validador sempre ligado)
- `src/quimia_ingestion/core/exceptions.py`, `integrations/extractor.py` (`ExtractorHTTPError`)
- `src/quimia_ingestion/workflows/ingest_fds.py` (seções obrigatórias, cache, 400/502)
- `src/quimia_ingestion/state/sqlite.py` (`image_state`)
- `src/quimia_ingestion/publishers/local_bd.py` (verificação, escrita atômica, chave marca+produto)
- `src/quimia_ingestion/workflows/enrich_images.py` (`ALREADY_PUBLISHED`, busca sem `24x`)
- `src/quimia_ingestion/images/background.py` (sessão única do `rembg`)
- `src/quimia_ingestion/images/matcher.py` (marca, outras marcas, kits, teto de revisão)
- `src/quimia_ingestion/domain/rules.py` (`other_brands`)
- `src/quimia_ingestion/discovery/factory.py`, `integrations/sitemap_sds.py` (SC Johnson removido)
- `src/quimia_ingestion/validation/pdf.py`, `integrations/search_sds.py` (nome do produto pelo cabeçalho)

Configuração:
- `config/brands.yaml` (`other_brands`, providers de Mr. Músculo)
- `.env.example`

Testes novos ou alterados:
- `tests/unit/test_db_guard.py`, `test_config_consistency.py`
- `tests/unit/test_matcher.py`, `test_images.py`, `test_public_providers.py`, `test_pdf_validator.py`, `test_cli.py`
- `tests/integration/test_ingestion_workflow.py`, `test_image_workflow.py`

Scripts e notas:
- `scripts/smoke_rembg.py`
- `NOTA_EXTRATOR_AI.md`

Documentos:
- `README.md`, `TEST_REPORT.md`, `CHANGELOG.md`, `SESSAO_2026-10-31.md`

## 3. Testes executados

Comando:
```text
python -m pytest -o addopts="" -q
```

| Conjunto | Resultado |
|---|---|
| Unitários (`tests/unit`) | 95 passando |
| Integração (`tests/integration`) | 26 passando |
| **Total** | **121 passando, 0 falhas** |

Histórico: 37 testes na v0.2.0, 58 ao fim de 31/10, 121 agora.

Os testes automatizados usam mocks. Não acessam Aiven, GitHub, ZenRows nem o extractor.

## 4. Testes reais

Todos feitos em ambiente local, sem escrita remota.

| Teste | Serviço | Custo |
|---|---|---|
| Descoberta Flora e Unilever (`discover-public`) | Sites públicos (HTTP direto) | Nenhum |
| Busca de imagens e FDS | ZenRows (Bing, DuckDuckGo) | Baixo (frações de crédito por busca) |
| Extractor em 29 FDS | `quimia-extractor-ai` local | LLM real na primeira rodada; depois, cache |
| Extractor em 10 FDS escolhidas | `quimia-extractor-ai` local | LLM real, ~45 s por PDF |
| Ingestão no Postgres local (`quimia-pg-test`) | Docker local | Nenhum |
| `rembg` em 12 fotos reais | Local (modelo `u2net`) | Nenhum |
| Segunda rodada de imagens sobre cópia do `quimia-bd` | Local | Nenhum |

Dados de teste deixados no Postgres local: linhas com marca `TESTE-CONTRATO` e `TESTE-ESTAB`. Não existem na Aiven.

## 5. Segurança

- **Aiven:** não houve nenhuma conexão de escrita. O `safety-check` com o `.env` real bloqueia o destino (código 1), e os comandos de escrita saem com código 2 antes de conectar.
- **GitHub:** sem push, PR nem API de escrita. Não há remote configurado.
- **Git:** nenhum commit, branch ou alteração de histórico.
- **`quimia-extractor-ai`:** não alterado. Só foi lido e chamado pela API local.
- **Credenciais:** nenhuma senha ou token foi impresso nos relatórios.

## 6. Idempotência

**Imagens (rodada real sobre cópia do `quimia-bd`, produto já publicado):**
- Primeira execução: `ALREADY_PUBLISHED`, com `state.db` novo.
- Segunda execução: `ALREADY_PUBLISHED`.
- Busca, download e `rembg`: 0 em ambas.
- Nenhum arquivo do `quimia-bd` alterado, nem em conteúdo nem em data de modificação.

**FDS (Postgres local, 29 respostas em cache):**
- Rodada 1: 7 gravadas, 22 em revisão, 1 duplicata por hash.
- Rodada 2 (mesmo `state.db`): 0 chamadas ao extractor, 0 linhas novas em nenhuma tabela.

**Limitação:** a primeira rodada de imagens com serviços reais não foi repetida depois das mudanças. Ela exigiria rebaixar o threshold, o que o plano proíbe. Está coberta por testes automatizados.

## 7. `rembg` — diagnóstico do `0xC0000409`

- **Ambiente:** Python 3.14.2, rembg 2.0.86, onnxruntime 1.31.1, Pillow 12.3.0, numpy 2.5.4.
- **Testes:** 3 processos separados com 1 chamada cada, 1 processo com 6 chamadas, e 12 fotos reais no mesmo processo. Nenhum crash.
- **Achado:** o código recarregava o modelo a cada imagem (~52 s cada). Corrigido com uma sessão reaproveitada, com saída idêntica pixel a pixel.
- **Conclusão:** o crash não foi reproduzido. Não é possível afirmar a causa. Se voltar, o comando é `python scripts/smoke_rembg.py --runs 5 --calls 6`.
- **Não testado:** Python 3.12 (o `pyproject` exige `>=3.12`, mas só há 3.14 instalado).

## 8. Pendências

1. **Extractor (bloqueio principal).** Dos 29 PDFs com cache, só 7 chegam completos. Das 10 FDS enviadas agora, 3 gravariam. Os demais dão HTTP 502 (9 casos), 400 (4) ou 504 (2). A causa do `SECÇÃO` e do 502 precisa ser tratada pelo mantenedor. Ver `NOTA_EXTRATOR_AI.md`.
2. **Nomes de produto.** O cabeçalho só existe nas FDS da Flora. Os nomes saem em caixa alta e abreviados, e precisam de curadoria antes do `quimia-bd`.
3. **Imagens.** Nenhuma das 23 FDS descobertas tem imagem acima de 0,90. O melhor score foi 0,80. Todas as imagens precisam de revisão humana.
4. **Mr. Músculo.** Sem fonte automática. Depende da manual inbox.
5. **504 do extractor.** Não é cacheado e é repetido a cada rodada, gastando LLM.
6. **PubChem.** Não iniciado (fora do escopo deste plano).
7. **Revisão.** Não existe fila nem ferramenta para revisar FDS ou imagens em revisão. Os resultados ficam no `state.db` e no retorno do comando.
8. **Python 3.12.** Não testado.

## 9. Riscos restantes

- **Volume baixo:** pelas amostras, espera-se algo como 25 a 30% das FDS sem revisão. Para as 23 descobertas, isso dá 6 a 7 registros automáticos. O número vem de 39 amostras e pode mudar.
- **Dependência do LLM:** os 502 não têm causa confirmada. Uma mudança no modelo ou no prompt pode mudar a taxa.
- **Dados de origem:** os nomes de produto e as versões vêm de cabeçalhos e rótulos variados. Podem sair erradas sem aviso.
- **Scores de imagem:** o matcher usa palavras. Variantes que só acrescentam palavras (ex.: "Multiuso" contra "Multiuso Cítrico") ainda passam como correspondência.
- **Sites externos:** os providers dependem do HTML de DuckDuckGo, Bing e dos sites dos fabricantes. Mudanças de layout zeram a busca sem erro explícito.
- **Ingestão na Aiven:** nunca foi testada, de propósito. A primeira escrita real precisa de autorização explícita.

## 10. Confirmação explícita

Nenhum commit, push, pull request, branch ou escrita em serviço remoto foi feito. Nenhuma escrita na Aiven ocorreu. O `quimia-extractor-ai` não foi modificado.
