"""Carga controlada do MVP: só entra produto com a cadeia completa; tudo o que entra é registrado e reversível.

Critérios (combinados com o time):
  - FDS com seções 03 (composição), 04 (primeiros socorros) e 10 localizadas e sem pendência de seção;
  - nome do produto revisado por uma pessoa (arquivo CSV com `aprovado=sim`);
  - imagem de fonte oficial com score >= 0,90 (checada fora deste módulo).
"""
from __future__ import annotations

import re

# Pendência nas seções 03/04 (qualquer motivo) tira o produto do MVP; na 10, só "não localizada".
SECOES_ESTRITAS = ("03", "04")
# Tabelas cujos ids são registrados para a reversão. O resto é conferido por hash do conteúdo.
TABELAS_CHAVE = ("marca", "produto", "fds", "substancia", "sinonimo_pendente")
# Trilha de auditoria do banco (triggers): só cresce. A carga e a reversão aparecem nela, e é isso que se quer.
SO_ACRESCENTA = frozenset({"log_auditoria"})
# Tabelas que a carga pode tocar (produto, FDS e o que o trigger materializa). Sem usuários nem sessões.
TABELAS_DA_CARGA = ("marca", "produto", "fds", "fds_composto", "fds_primeiro_socorro", "fds_incompatibilidade",
                    "fds_descarte", "sinonimo_pendente", "substancia", "log_auditoria")


# Política B: o documento simplesmente não informa CAS/concentração (comum em produto de limpeza). Isso não
# exclui; dado contraditório, nome ambíguo ou composição/primeiros socorros ausentes continuam excluindo.
CAMPOS_DO_COMPOSTO = frozenset({"cas_numero", "concentracao", "concentracao_min", "concentracao_max", "unidade_concentracao"})
MOTIVOS_DE_AUSENCIA = frozenset({"informacao_ausente", "documento_nao_especifica", "termo_ambiguo"})


def _ausencia_do_documento(pendencia: dict) -> bool:
    return pendencia["secao"] == "03" and pendencia["campo"] in CAMPOS_DO_COMPOSTO and pendencia["motivo"] in MOTIVOS_DE_AUSENCIA


def motivos_exclusao(extraction: dict) -> list[str]:
    """Lista vazia = a extração cumpre os critérios de FDS do MVP."""
    secoes = extraction.get("secoes", {})
    s3, s4, s10 = (secoes.get(k, {}) for k in ("03", "04", "10"))
    motivos = []
    if not (s3.get("encontrada") and s3.get("compostos")):
        motivos.append("seção 03 sem composição")
    if not (s4.get("encontrada") and s4.get("primeiros_socorros")):
        motivos.append("seção 04 sem primeiros socorros")
    if not s10.get("encontrada"):
        motivos.append("seção 10 não localizada")
    for p in extraction.get("pendencias", []):
        if p["motivo"] == "secao_nao_localizada":
            motivos.append(f"seção {p['secao']} não localizada")
        elif p["secao"] in SECOES_ESTRITAS and not _ausencia_do_documento(p):
            motivos.append(f"pendência {p['secao']}/{p['campo']} ({p['motivo']})")
    return list(dict.fromkeys(motivos))


_PALAVRAS = {
    "DET": "Detergente", "DET.": "Detergente", "PO": "Pó", "PÓ": "Pó", "SABAO": "Sabão", "SABÃO": "Sabão",
    "LOUCAS": "Louças", "LOUÇAS": "Louças", "MACA": "Maçã", "MAÇÃ": "Maçã", "TRIPLACAO": "Triplação",
    "TRIPLAÇÃO": "Triplação", "ACAO": "Ação", "AÇÃO": "Ação", "GLICERINADO": "Glicerinado",
}
_MINUSCULAS = {"DE", "DA", "DO", "EM", "PARA", "E", "COM"}
_CAIXA = re.compile(r"\b(\d+)\s*X\s*(\d+(?:[.,]\d+)?)\s*(ML|G|KG|L)\b", re.I)
_UNIDADE = {"ML": "mL", "G": "g", "KG": "kg", "L": "L"}


def propor_nome(nome_fds: str, marca: str) -> str:
    """Rascunho do nome para o banco (sem a marca, como em "Detergente Lava Louças Neutro 24x500mL").

    É só um ponto de partida: quem aprova é a pessoa que revisa o CSV.
    """
    nome = _CAIXA.sub(lambda m: f"{m[1]}x{m[2]}{_UNIDADE[m[3].upper()]}", nome_fds)
    palavras = []
    for palavra in nome.split():
        chave = palavra.upper()
        if chave == marca.upper():
            continue
        if palavra == palavra.upper() and chave in _PALAVRAS:
            palavras.append(_PALAVRAS[chave])
        elif chave in _MINUSCULAS:
            palavras.append(chave.lower())
        elif re.fullmatch(r"\d+x\d+.*", palavra):
            palavras.append(palavra)
        else:
            palavras.append(palavra.capitalize() if palavra == palavra.upper() else palavra)
    return " ".join(palavras).replace("( ", "(")


def _tabelas(conn) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
        return [r[0] for r in cur.fetchall()]


def snapshot(repo, tabelas=None) -> dict[str, str]:
    """Contagem + hash do conteúdo de cada tabela: prova de que a reversão devolveu o banco ao que era.

    Em banco com uso real, passe `tabelas` (TABELAS_DA_CARGA): hashear tudo leria dados de usuários e acusaria
    mudanças que não são da carga.
    """
    with repo._connect() as conn:
        out = {}
        existentes = _tabelas(conn)
        for tabela in (tabelas or existentes):
            if tabela not in existentes:
                continue
            with conn.cursor() as cur:
                cur.execute(f"""SELECT count(*), md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM "{tabela}" t""")
                total, digest = cur.fetchone()
            out[tabela] = f"{total}:{digest}"
        return out


def _ids(repo, tabelas=TABELAS_CHAVE) -> dict[str, set[int]]:
    with repo._connect() as conn, conn.cursor() as cur:
        out = {}
        for tabela in tabelas:
            cur.execute(f'SELECT id FROM "{tabela}"')
            out[tabela] = {r[0] for r in cur.fetchall()}
        return out


def carregar(repo, itens: list[dict], tabelas=None) -> dict:
    """Grava os itens e devolve o registro do que ESTA carga criou (ids), com o estado anterior do banco.

    O que foi criado vem do que a própria carga devolveu, não de uma diferença antes/depois: num banco com
    outras pessoas gravando, a diferença atribuiria linhas alheias à carga (e a reversão as apagaria).
    Cada item: marca, nome, versao, data_atualizacao, fonte_url, raw_json (e, opcional, tipo_produto).
    """
    antes_snapshot, antes_ids = snapshot(repo, tabelas), _ids(repo)
    gravados, produtos, fds_ids = [], [], []
    for item in itens:
        if repo.find_fds_by_source_url(item["fonte_url"]):
            gravados.append({"fonte_url": item["fonte_url"], "resultado": "JA_EXISTIA"})
            continue
        produto_id = repo.get_or_create_product(item["marca"], item["nome"], item.get("tipo_produto", "outro"))
        fds_id = repo.insert_fds(produto_id, item["versao"], item["data_atualizacao"], item["fonte_url"], item["raw_json"])
        produtos.append(produto_id)
        fds_ids.append(fds_id)
        gravados.append({"fonte_url": item["fonte_url"], "produto_id": produto_id, "fds_id": fds_id, "resultado": "GRAVADO"})
    with repo._connect() as conn, conn.cursor() as cur:
        novos_produtos = sorted(set(produtos) - antes_ids["produto"])
        cur.execute("SELECT DISTINCT id_marca FROM produto WHERE id = ANY(%s)", (novos_produtos,))
        novas_marcas = sorted({r[0] for r in cur.fetchall()} - antes_ids["marca"])
        cur.execute("SELECT id FROM sinonimo_pendente WHERE id_fds = ANY(%s)", (fds_ids,))
        sinonimos = sorted(r[0] for r in cur.fetchall())
    depois_ids = _ids(repo, ("substancia",))
    return {
        "snapshot_antes": antes_snapshot,
        "tabelas": list(tabelas) if tabelas else None,
        "criado": {"fds": sorted(fds_ids), "produto": novos_produtos, "marca": novas_marcas, "sinonimo_pendente": sinonimos},
        # Nunca apagada pela reversão: só avisa se a carga (ou outra pessoa) criou substâncias.
        "substancia_nova_alerta": sorted(depois_ids["substancia"] - antes_ids["substancia"]),
        "itens": gravados,
    }


def reverter(repo, registro: dict) -> dict[str, str]:
    """Apaga só o que o registro diz que a carga criou e devolve as tabelas que NÃO voltaram ao estado anterior."""
    criado = registro["criado"]
    # fds primeiro (as tabelas filhas caem em cascata); produto antes de marca.
    ordem = ("fds", "sinonimo_pendente", "produto", "marca")
    with repo._connect() as conn, conn.cursor() as cur:
        for tabela in ordem:
            if criado.get(tabela):
                cur.execute(f'DELETE FROM "{tabela}" WHERE id = ANY(%s)', (criado[tabela],))
    atual = snapshot(repo, registro.get("tabelas"))
    return {t: f"antes={registro['snapshot_antes'][t]} depois={atual.get(t)}"
            for t in registro["snapshot_antes"]
            if t not in SO_ACRESCENTA and atual.get(t) != registro["snapshot_antes"][t]}
