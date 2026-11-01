# Relatório — Frente 2 (parte 2): provider oficial de imagens

Data: 2026-11-01. Repositório alterado: `quimia-ingestion-service`. Nada commitado. Sem escrita na Aiven, no `quimia-bd` real ou no GitHub. OMO e Mr. Músculo ficam sem fonte oficial, como combinado.

Written for: o time do Quimia.

## 1. Resumo

Com o limiar de produção (**0,90, sem reduzir nada**), 3 de 7 produtos de teste foram publicados automaticamente, todos corretos, com score 0,97. Na segunda rodada, 0 downloads, 0 `rembg` e nenhum arquivo alterado. Antes disso a publicação automática era zero.

| Produto de teste | Resultado | Motivo |
|---|---|---|
| Minuano Detergente Lava Louças Neutro | **Publicado (0,97)** | Existe na loja com o mesmo nome |
| Brisa Detergente Lava Louças Maçã | **Publicado (0,97)** | Idem |
| Minuano Detergente Lava Louças Coco | **Publicado (0,97)** | Idem |
| Assim Detergente Lava Louças Neutro | Revisão (0,77) | A loja não tem esse produto |
| Minuano Amaciante Concentrado Azul | Revisão (0,77) | Na loja o "azul" se chama "Clássico" |
| Minuano Detergente em Pó Floral 900 g | Revisão (0,69) | Na loja é "Sabão/Lava-roupas em pó", com 800 g e outros pesos |
| Assim Detergente em Pó Tripla Ação 500 g | Revisão (0,69) | Na loja é "Lava-roupas pó Assim **Triplacao**", 400 g e 800 g |

Nenhum falso positivo: os 4 que não casam por nome caíram em revisão, não em publicação. Os 3 PNGs foram conferidos visualmente: packshots oficiais limpos, 1254×1254, RGBA, transparência real.

## 2. Como funciona

- `integrations/flora_store.py` (novo): `FloraStoreImageSearch` lê o sitemap da loja oficial (`compraflora.com.br`, Nuvemshop, ~750 produtos, uma leitura por execução) e escolhe até 5 páginas com mais palavras em comum com a busca (mínimo 60%; empate vai para o slug com menos palavras sobrando). De cada página usa `og:title` e `og:image`, e pede a foto em 1024 px.
- `ChainedImageSearch`: loja oficial primeiro, depois o Bing. O matcher continua decidindo o score; nada foi afrouxado.
- A loja não expõe JSON-LD do produto da própria página (só dos relacionados), por isso o parser usa Open Graph.
- Ligado em `enrich-images` (`cli.py`).

## 3. Mudanças de regra que merecem sua atenção

1. **`compraflora.com.br` conta como domínio oficial para imagem.** Está em `image_domains` (`config/brands.yaml`, para Minuano, Assim e Brisa), separado de `official_domains`. Motivo: `official_domains` também dirige a busca de FDS (uma busca `site:` por domínio e score 90 para qualquer link), e a loja não é fonte de FDS. A loja é linkada pelo site oficial da Flora. **Confirme se o time aceita a loja como fonte oficial.**
2. **Gate de qualidade: o tamanho mínimo agora usa o maior lado do produto**, não o menor (`images/quality.py`). Antes, qualquer garrafa alta e estreita era barrada como "pequena demais" (as garrafas reais medem ~227×956 px). O valor padrão (256) não mudou; o comentário do `.env.example` foi ajustado. Teste novo: `test_tall_narrow_bottle_is_not_rejected_as_small`.

## 4. Testes

- 121 → **129 passando** (102 unitários, 27 de integração), 0 falhas. Novos: 6 do provider (`tests/unit/test_flora_store.py`, com `httpx.MockTransport`, sem rede), 1 do gate, e os da frente anterior.
- Teste real: Postgres local, `state.db` e cópia do `quimia-bd` novos, ZenRows e loja reais. Os produtos de teste criados no Postgres local foram removidos (24 produtos e 3 marcas, como antes).

## 5. Riscos e limites

- **Depende do HTML da loja** (sitemap e tags `og:`). Se a Nuvemshop mudar o formato, a loja devolve 0 candidatos e o fluxo cai para o Bing, que nunca passa de 0,88, ou seja, tudo vai para revisão sem erro explícito. O campo `candidates` do `REVIEW_REQUIRED` ajuda a notar isso.
- **Variantes que só acrescentam palavras** ainda podem empatar (ex.: "Multiuso" contra "Multiuso Cítrico"). O desempate favorece o nome mais curto, mas a ambiguidade existe.
- **Lacunas de nome**, vistas nos 4 negativos: "detergente em pó" contra "lava-roupas/sabão em pó", "Tripla Ação" contra "Triplacao", e pesos diferentes (500/900 g contra 400/800 g). Hoje isso vira revisão manual.
- Cada execução lê o sitemap (600 KB) e até 5 páginas por produto. Não há cache entre execuções.

## 6. Cobertura medida e sinônimos (atualização)

Medição sobre as **19 FDS de Minuano, Assim e Brisa** da descoberta pública de hoje (nomes lidos do cabeçalho, em CAIXA ALTA), buscando na loja real, sem publicar nada:

| Etapa | Auto-aprovados (≥ 0,90) |
|---|---|
| Provider oficial, matcher anterior | **3 de 19** |
| + multiplicador em maiúscula (`24X500 ML`, `6X2L`) | — |
| + sinônimos (`DET.` = detergente; detergente/sabão/lava-roupas **em pó**; `Tripla Ação` = `Triplação`) | 10 de 19 |
| + título precisa conter o produto em site oficial | **9 de 19** |

- **O maior ganho não foi sinônimo, foi o bug da maiúscula**: as FDS trazem `24X500 ML` e o `search_name` só removia `x` minúsculo, então quase todo produto das FDS caía em 0,69.
- **Sinônimos valeram cerca de 4 produtos** (todos de detergente em pó da Assim). O peso não entra na equivalência: 400 g e 800 g seguem diferentes.
- **Falso positivo evitado:** "Detergente em Pó Assim Floral" casava com uma página cujo título diz "Micelar" e cuja URL diz `triplacao-floral`. A palavra só aparecia na URL. Em domínio oficial, o título agora precisa conter todas as palavras do produto (teste em `test_matcher.py`).
- Os 10 que seguem em revisão são, em geral, corretos: peso diferente (`20X1KG` contra 160 g), produto que a loja não tem (ex.: Assim Antibac), `(Leitoso)` no nome, código `1300` no nome.
- **Limite:** amostra de 19 produtos e 3 marcas. Quando o nome da FDS não traz peso e a loja tem vários (400 g, 800 g, 1,6 kg), os três empatam e a escolha entre eles é arbitrária (a mesma arte, outro tamanho de pacote).
- Testes: **134 passando** (107 unitários, 27 de integração).

## 7. Próximos passos sugeridos

1. Fila de revisão com os melhores candidatos (a loja já devolve foto limpa para sugerir na revisão).
2. Rodar sobre mais produtos da Flora (as 47 FDS locais e o catálogo da loja) para medir a taxa de publicação automática com uma amostra maior que 19.
