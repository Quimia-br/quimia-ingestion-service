# Nota técnica para o mantenedor do quimia-extractor-ai

Origem: testes do ingestion service com 29 FDS reais (respostas em cache). Nenhuma alteração foi feita no repositório do extractor.

## 1. Título "SECÇÃO N" não reconhecido (`app/pdf/secoes.py`)

- **Comportamento atual:** `_NUMERO_TITULO` aceita o prefixo `(?:secao|section)`. Depois do `_normalizar` (NFKD + remoção de acentos), "SECÇÃO" vira `seccao`, que não casa.
  Verificado chamando `_identificar_titulo`: `"SECÇÃO 3 - COMPOSIÇÃO"` → `None`; `"SEÇÃO 3 - COMPOSIÇÃO"` → `(3, 1)`.
- **Efeito:** com todos os títulos nessa grafia, a rota devolve 400 ("Nenhuma das seções 3, 4 ou 10 foi localizada"). Com a grafia só em parte dos títulos, devolve 200 com seções `encontrada: false`/vazias (sucesso aparente).
- **Esperado:** reconhecer `seção`, `secção` e `section` (sem diferenciar maiúsculas/minúsculas e acentos). Sugestão: `(?:sec+ao|section)`.
- **Testes sugeridos** (`_identificar_titulo`, com a linha seguinte `None`):
  `"SEÇÃO 3 - COMPOSIÇÃO"`, `"SECÇÃO 3 - COMPOSIÇÃO"`, `"Secção 4 – Primeiros socorros"`, `"SECTION 3 - COMPOSIÇÃO"`, `"seção 10: estabilidade"` → todos devem retornar o número da seção.
  Contraexemplo que deve continuar `None`: `"Veja a seção 3 deste documento"` (título no meio da frase).
- Observação: `"SECTION 3: Composition"` continua sem casar porque os padrões de título são só em português (`composicao`); se FDS em inglês forem alvo, é outro ajuste.

## 2. 502 `EvidenciaInvalida` (`app/validators/extracao.py`)

- **Dados em cache:** 9 de 29 PDFs retornaram 502 com `detail: "A IA não devolveu uma extração válida."` (23–41 s cada, ou seja, o LLM foi chamado). A resposta HTTP não inclui qual citação falhou, então **não há exemplo literal de evidência** no cache; atribuir a causa a `EvidenciaInvalida` vem da leitura do código (`routes/extracoes.py` agrupa `ErroLLM`, `EvidenciaInvalida` e `ValidationError` no mesmo 502), não de uma prova por caso.
- **Para obter exemplos concretos** sem relaxar nada: logar (no servidor do extractor) o `texto_evidencia`, a página e o trecho mais próximo do texto-fonte quando `validar_evidencias` levanta, e separar o `detail` do 502 por tipo de causa.
- A validação literal deve ser mantida; ela impede o LLM de inventar conteúdo.
