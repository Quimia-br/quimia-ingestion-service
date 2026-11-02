# Relatório — ensaio do MVP (carga controlada)

Data: 2026-11-01. Escopo: ensaiar, num Postgres **local**, a carga de "só produto com a cadeia completa", com registro e reversão. Sem escrita na Aiven, no `quimia-bd` real ou no GitHub.

Written for: o time do Quimia.

## 1. Resumo

| Item | Resultado |
|---|---|
| Mecânica de carga | **Funciona.** Produto, FDS e tabelas filhas (via trigger) gravados e registrados |
| Idempotência | **Funciona.** Segunda carga: 0 criações |
| Reversão | **Funciona**, inclusive ligada a marca e produto que já existiam; banco idêntico ao anterior (tabela por tabela, por hash) |
| Critérios aprovados (FDS completa + imagem oficial ≥ 0,90) | **Só 2 de 19 produtos passam** |
| Ensaio contra o schema da Aiven | **Não feito.** Falta o schema (seção 5) |

## 2. O que foi construído

- `src/quimia_ingestion/mvp.py`: critérios de FDS (`motivos_exclusao`), rascunho de nome (`propor_nome`), carga com registro dos ids criados (`carregar`) e reversão com prova de integridade (`reverter`). Testes dos critérios e do nome em `tests/unit/test_mvp.py`. A suíte está em **146 passando**.
- Scripts do ensaio (em `%TEMP%\qi-run\ensaio`, ainda não no repo): extração das FDS, avaliação, carga e reversão. A carga **reavalia os critérios a partir do cache** e só grava itens com `aprovado=sim` no CSV de nomes; o CSV aprova o nome, não substitui o critério.
- Banco do ensaio: `quimia_ensaio`, clonado do schema local, com 1 produto e 1 FDS preexistentes para provar que a reversão não os toca.

## 3. Resultado por etapa

**Extração (19 FDS de Minuano, Assim e Brisa, LLM real, prazo largo só no ensaio):** 16 completas (seções 3 e 4 com conteúdo), 3 com HTTP 502.
- **Nenhum 504.** Com prazo largo (300 s no extractor), a latência do provedor deixa de derrubar a extração. Para o ingestion, que chama o extractor direto, isso resolve o 504 sem trocar de modelo: basta uma instância do extractor com `EXTRATOR_TIMEOUT_SECONDS` maior (o teto de 60 s é da quimia-api, não do ingestion). Não aplicado em produção.
- **Os 3 × 502 são erros reais do LLM, não de formatação.** O PDF diz "Administr**ar** oxigênio" e o LLM escreveu "Administr" e "Administrando"; o terceiro foi uma resposta malformada do provedor. A validação acertou em recusar. Esses vão para revisão.

**Critérios do MVP:**

| Política | Entram |
|---|---|
| A, a aprovada: qualquer pendência nas seções 03/04 exclui | **2** (Sabão Barra Neutro; Detergente Pó Triplação) |
| B: tolera CAS e concentração ausentes **no documento** | 4 |
| C: exige só as seções | 8 linhas (4 produtos distintos; vários são versões da mesma FDS) |

O motivo quase sempre é o mesmo: pendências de "CAS ausente" ou "concentração não especificada" na seção 3. São ausências reais do documento (FDS de produto de limpeza costuma não trazer), não falha do extractor. A política A é muito rígida para esse tipo de produto. **Decisão sua**, ver seção 6.

**Carga e reversão (política A, 2 itens, depois o caso difícil com 4):**
- A carga criou 1 marca, 2 produtos, 2 FDS e 1 sinônimo pendente; o trigger materializou 14 compostos, 12 primeiros socorros e 2 incompatibilidades.
- No caso difícil, o Minuano Neutro (produto que já existia) ganhou uma segunda FDS; a reversão removeu só a FDS nova.
- `log_auditoria` cresce por trigger (cada INSERT e DELETE de FDS fica registrado). Isso é desejável e a verificação agora trata essa tabela como só-acrescenta. Todas as outras tabelas voltaram idênticas.

## 4. Lacunas que o ensaio expôs

1. **`tipo_produto` fica sempre `outro`** e a descrição é "Importado automaticamente a partir de FDS." (valores fixos em `postgres.py`). Para um MVP que o time vai ver, o tipo precisa vir do CSV de revisão.
2. **`foto_url` fica nulo.** A imagem só chega pelo seed do `quimia-bd`. O ensaio verificou que existe imagem oficial ≥ 0,90 para os 2 itens, mas **não gerou nem publicou os PNGs** deles. O vínculo produto–imagem do MVP ainda precisa do `enrich-images` sobre os nomes finais e do commit no `quimia-bd`.
3. **Nome do produto:** o rascunho automático tira a marca, expande abreviações e normaliza `24X500 ML` para `24x500mL`. Não recupera acentos nem decide o nome comercial (a loja chama de "Sabão Barra Multiuso Neutro Assim Triplação 160g"). A revisão humana é obrigatória, como combinado.
4. **Versões da mesma FDS:** vários itens são a mesma FDS em versões diferentes (ex.: Detergente Lava Louças Neutro aparece 3 vezes). O MVP precisa escolher a versão mais recente por produto; hoje a carga trata cada uma como uma FDS (válido no schema, mas confunde a revisão).
5. **Git:** `src/quimia_ingestion/integrations/__init__.py` ficou fora do commit inicial (aparece como não rastreado). `mvp.py` e `test_mvp.py` também ainda não estão commitados.

## 5. O que falta para ensaiar contra a Aiven

O `quimia_ensaio` foi clonado do schema montado a partir do checkout local do `quimia-bd`. **Não sei se o schema, os triggers e os dados de referência da Aiven são idênticos.** Para fechar isso preciso de um dos dois, e a escolha é sua:
- um `pg_dump --schema-only` da Aiven (e, se possível, `substancia` e classes químicas), restaurado em Postgres local; ou
- autorização explícita para uma conexão **somente leitura** à Aiven, só para extrair o schema.

Sem isso, o ensaio prova a mecânica, não a compatibilidade.

## 6. Decisões e próximos passos

1. **Política de aceite.** A (2 produtos), B (4) ou C (8 linhas)? Minha sugestão: B, com a regra escrita no CSV de revisão e a pendência visível para quem revisa.
2. **Tipo do produto** e descrição: vir do CSV de revisão (campo `tipo_produto`).
3. **Versão por produto:** carregar só a mais recente.
4. **Schema da Aiven** (seção 5).
5. Transformar os scripts do ensaio em comandos do CLI (`mvp-avaliar`, `mvp-carregar`, `mvp-reverter`) e commitar `mvp.py` e `test_mvp.py`.
6. Gerar os PNGs dos itens aprovados e fechar o par produto–imagem no `quimia-bd`.

## 7. Carga e reversão reais na Aiven (2026-11-01)

Autorizadas explicitamente. Itens: Minuano "Detergente Lava Louças Neutro 24x500mL" e Assim "Detergente Pó Triplação Micelar" (política B, imagem oficial 0,97 nos dois).

| Etapa | Resultado |
|---|---|
| Preflight somente leitura (`read_only`) | Aiven: PostgreSQL 18.6; 93 marcas, 11 produtos, 8 FDS |
| Carga (`scripts/mvp_carga.py carregar --executar`) | 2 marcas, 2 produtos, 2 FDS, 3 sinônimos pendentes criados |
| Trigger | Materializou 4 e 5 compostos, 4 e 4 primeiros socorros, 3 e 2 incompatibilidades |
| Reversão (`reverter --executar`) | Tabelas da carga idênticas ao estado anterior (por hash do conteúdo) |
| Conferência final | Contagens iguais às do preflight; só `log_auditoria` cresceu (+4 linhas: 2 INSERT e 2 DELETE de FDS) |

O schema da Aiven foi comparado antes: triggers, as 3 funções (`fn_processar_fds_raw_json`, `fn_trg_processar_fds_raw_json`, `fn_auditoria`, iguais sem contar espaçamento), colunas e constraints batem com o ensaio.

**Efeitos que a reversão não desfaz:** (1) a trilha de auditoria registra a carga e a reversão (desejável); (2) as sequências de ids avançaram (produtos 146 e 147, marcas 94 e 95 foram consumidos; uma carga futura começa depois); (3) por alguns minutos os 2 produtos ficaram visíveis para qualquer um que consultasse o banco.

**Mudanças no código desta etapa:**
- `postgres.py`: `allow_remote_host` libera **um** host, nomeado por inteiro; `PGHOSTADDR`, `PGSERVICE` e `DATABASE_URL` continuam bloqueados. A trava geral segue ativa para todo o resto. 2 testes novos.
- `mvp.py`: o registro de reversão passou a listar só o que **a própria carga devolveu**, e não uma diferença de ids antes/depois (que, em banco com outras pessoas gravando, poderia incluir linhas de terceiros e apagá-las). `substancia` nunca é apagada pela reversão. O snapshot se limita às tabelas da carga (`TABELAS_DA_CARGA`), sem ler usuários nem sessões.
- `scripts/mvp_carga.py`: exige `--permitir-host` igual ao host do `.env`; só mostra o plano sem `--executar`; recusa nova carga se já há registro; recusa gravar o registro dentro do repo.
- O registro de reversão desta carga está fora do repo, em `%USERPROFILE%\quimia-registros\carga_aiven_2026-11-01.json`. Pode ser apagado: a reversão já foi executada.
- Suíte: **151 passando**.

**Descoberta sobre o catálogo da Aiven (decisão pendente):** os 11 produtos reais estão cadastrados sob a marca **"Flora"**, com `tipo_produto` classificado, descrição e `foto_url`. As outras 92 marcas parecem dados fictícios. Nossa carga cadastra por marca de consumo (Minuano, Assim, criando 2 marcas novas), com `tipo_produto='outro'` e descrição "Importado automaticamente". Antes de uma carga que **fique**, o time precisa decidir: (a) marcas Minuano e Assim, ou (b) tudo sob "Flora", com o nome carregando a marca; e de onde vêm `tipo_produto` e a descrição.

## 8. Carga definitiva na Aiven (2026-11-01) — alternativa (a)

Decisão do time: marcas Minuano e Assim (alternativa a). Sem reversão desta vez.

| Item | Aiven |
|---|---|
| Minuano · Detergente Lava Louças Neutro 24x500mL | marca 96, produto 148, FDS 11 (v03): 4 compostos, 4 primeiros socorros, 3 incompatibilidades; `limpeza_geral` |
| Assim · Detergente Pó Triplação Micelar | marca 97, produto 149, FDS 12 (v08): 5 compostos, 4 primeiros socorros, 2 incompatibilidades; `limpeza_geral` |

- `tipo_produto` agora vem do CSV de revisão (`limpeza_geral`, como o produto 5 "Detergente Líquido" já existente), em vez do `outro` fixo. A descrição segue "Importado automaticamente a partir de FDS." — vale revisar.
- Registro de reversão: `%USERPROFILE%\quimia-registros\carga_aiven_definitiva_2026-11-01.json` (fora do repo; guardar). Desfazer: `python scripts/mvp_carga.py reverter --permitir-host <host do .env> --registro <arquivo> --executar`.
- **Imagens (par produto–imagem):** geradas pelo limiar de produção (0,90, score 0,97, loja oficial da Flora) num **diretório de staging**, `%USERPROFILE%\quimia-registros\bd_staging`, e **não** no checkout do `quimia-bd`: ele tem trabalho não commitado na branch `fix/QUI-1dfbyc94eyy`. Conteúdo: 2 PNGs 1254×1254 RGBA, `manifest_produtos.json` e `seed_produto.csv` com as 2 linhas novas (a `foto_url` só passa a resolver depois do push do `quimia-bd` na `main`).
- Pendente do lado do `quimia-bd`: copiar os 2 PNGs para `src/database/assets/produtos/`, acrescentar as 2 linhas ao `seed_produto.csv` e (opcional) o manifest. As linhas novas do seed têm `descricao` vazia.
- `produto.foto_url` na Aiven segue nulo para os 2 produtos até a carga do seed. O serviço não atualiza `foto_url` no banco, por decisão anterior.

## 9. Segunda leva na Aiven (2026-11-01): fecha os 4 itens da política B

| Item | Aiven |
|---|---|
| Assim · Sabão Barra Neutro | produto 150, FDS 13 (v0.0): 2 compostos, 4 primeiros socorros, 0 incompatibilidades; `limpeza_geral` |
| Assim · Detergente Pó Triplação | produto 151, FDS 14 (v09): 3 compostos, 4 primeiros socorros, 0 incompatibilidades; `limpeza_geral` |

- Marca Assim já existia (97): nenhuma marca nova. Totais na Aiven depois: 95 marcas, 15 produtos, 12 FDS.
- Registro de reversão: `%USERPROFILE%\quimia-registros\carga_aiven_definitiva_2_2026-11-01.json`. As duas levas têm registros separados: reverter uma não toca a outra.
- Os 2 nomes foram carregados como propostos; o time ajusta depois. **Renomear no banco exige renomear também**, no `quimia-bd`: o arquivo do PNG, a linha do `seed_produto.csv` e a chave do `manifest_produtos.json` (todos derivam de marca + nome).
- Imagens no staging (`%USERPROFILE%\quimia-registros\bd_staging`): 4 PNGs 1254×1254 RGBA, 4 linhas novas no seed.
- **Atenção em "Detergente Pó Triplação":** a foto veio da página "Lava Roupas Pó Assim Triplação 400g" da loja oficial, e a embalagem mostra a variante **Bicarbonato**. O nome do produto não cita variante, então o par é coerente com a FDS (que cobre a linha), mas vale conferir se é a imagem que o time quer. As outras 3 imagens batem com o nome.
- Seções 10 sem incompatibilidades listadas (0) nos dois itens: a seção foi localizada e o documento não as especifica; é o comportamento esperado (pendência de seção 10 não exclui na política B).
