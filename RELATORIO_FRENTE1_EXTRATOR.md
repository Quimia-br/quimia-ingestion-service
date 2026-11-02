# Relatório — Frente 1: quimia-extractor-ai

Data: 2026-11-01. Repositório alterado: `quimia-extractor-ai` (`Quimia/extractor-ai/quimia-extractor-ai`). Nada commitado. Modelo e configuração do LLM **não** foram alterados.

Written for: o time do Quimia e quem mantém o `quimia-extractor-ai`.

## 1. Resumo

| Item | Situação | Resultado |
|---|---|---|
| `SECÇÃO N` (grafia PT-PT) | **Corrigido** | 25 → 35 das 50 FDS locais com seções 3 e 4 localizadas (só detecção, sem LLM) |
| 502 `EvidenciaInvalida` | **Causa confirmada com chamada real; 3 tipos corrigidos** | 1 FDS que dava 502 agora passa. As outras 8 não foram retestadas |
| 504 (prazo de 55 s) | **Causa medida, sem correção possível sem mudar modelo/provedor** | Latência do provedor, não do tamanho da entrada |

## 2. O que mudou

- `app/pdf/secoes.py`: o prefixo do título aceita `sec+ao` ("SECÇÃO" vira "seccao" depois de tirar acentos).
- `app/validators/extracao.py`:
  - a mensagem de `EvidenciaInvalida` diz seção, página e citação (só no log; a resposta HTTP continua genérica);
  - a comparação de citações ignora **acentos e espaços**;
  - uma citação com trechos unidos por `" / "` vale se **cada trecho** existir literalmente.
- `app/routes/extracoes.py`: o log do 502 inclui essa mensagem (só para `EvidenciaInvalida`).
- Testes: 104 → **111 passando**, 0 falhas.

## 3. 502 — o que o log mostrou

Chamada real com o amaciante Minuano azul (que dava 502). Cada tentativa falhou por um motivo diferente, e o log novo apontou o trecho exato:

| # | Citação do LLM contra o PDF | Tipo | Tratamento |
|---|---|---|---|
| 1 | "após inala**c**ao" contra "inala**çã**o" | Acento removido pelo LLM | Comparação sem acentos |
| 2 | "**causar**" contra "**ca usar**" (e "tosse," contra "tosse ,") | O LLM corrigiu defeito de espaço da extração do PDF | Comparação sem espaços |
| 3 | `linha A / linha B` | O LLM juntou duas linhas da tabela com " / " | Cada trecho deve existir literalmente |

Depois dos três ajustes, o serviço completo (LLM real + validação) devolveu `processado_com_pendencias` em 44 s.

**Decisão que muda a regra de segurança:** a validação deixou de ser estritamente literal. Continua exigindo as **mesmas letras, na mesma ordem**, em trechos que existam no PDF, então não deixa passar conteúdo inventado (há teste para isso). Mas uma citação armazenada pode vir sem acento ou sem o espaço original. Se preferirem manter o rigor total, é só reverter `_normalizar_citacao` e `_citacao_existe`.

**Limite da evidência:** um PDF foi testado. O LLM varia de uma chamada para outra, então pode haver outros tipos de divergência nos demais 8 PDFs que deram 502. O log novo mostra qual é, caso apareça.

## 4. 504 — o que foi medido

Mesma FDS, as 3 chamadas ao LLM em paralelo, sem prazo:

| Seção | Texto enviado | Tempo |
|---|---|---|
| 3 (composição) | 274 caracteres | 46 s |
| 4 (primeiros socorros) | 2.183 caracteres | 116 s |
| 10 (incompatibilidades) | 647 caracteres | 17 s |

- A entrada é minúscula e ainda assim leva dezenas de segundos: o gargalo é o modelo/provedor (`xiaomi/mimo-v2.6-flash`).
- Os 116 s da seção 4 indicam um retry interno do SDK depois do timeout de 60 s (`LLM_TIMEOUT_SECONDS=60`, `LLM_MAX_RETRIES=2`).
- Em chamadas reais pela rota, a mesma FDS levou 42 s, 51 s e passou do prazo (57 s, 504). Variação grande entre chamadas.
- Com o modelo e as configurações fixos, **não há correção no código do extractor**: o prazo de 55 s tem teto de 60 s imposto pela quimia-api.

Opções que ficam fora do que foi permitido (modelo/esforço de raciocínio): trocar de modelo ou de provedor, ou aumentar o prazo da quimia-api. Do lado do ingestion, o que dá para fazer é tratar o 504 como falha temporária e repetir com intervalo (hoje repete sem cache, gastando LLM).

## 5. Efeito no ingestion

- O `NOTA_EXTRATOR_AI.md` do ingestion dizia que o extractor não foi alterado. Isso deixa de valer.
- O ingestion ainda não foi rodado contra o extractor alterado.

## 6. Pendências

1. Retestar as outras 8 FDS que deram 502 (cada uma custa de 45 s a 2 min de LLM).
2. Decidir se a validação mais tolerante (seção 3) é aceitável para o time.
3. Subseções numeradas (`4.1`, `3.2`) na detecção de título (`Espuma de limpeza 400ml`).
4. 504: depende de modelo/provedor/prazo da quimia-api.
5. Commit do extractor: fica com o time.
