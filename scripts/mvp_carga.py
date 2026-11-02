"""Carga controlada do MVP no banco configurado no .env (hoje a Aiven), com registro de reversão.

Uso (de dentro do repo, com o venv do projeto):
  python scripts/mvp_carga.py carregar  --permitir-host <host do .env> --registro <arquivo.json> --aprovados nomes.csv --avaliacao avaliacao.json [--executar]
  python scripts/mvp_carga.py reverter  --permitir-host <host do .env> --registro <arquivo.json> [--executar]

Sem --executar só mostra o plano (e lê o banco). A trava geral de escrita remota continua ativa: este script
libera UM host, escrito por inteiro, e só para si.
O registro de reversão contém ids do banco: fica FORA do repo (o script recusa gravá-lo dentro dele).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

from quimia_ingestion.core.config import Settings
from quimia_ingestion.integrations.postgres import PostgresQuimiaRepository
from quimia_ingestion.mvp import TABELAS_DA_CARGA, carregar, motivos_exclusao, reverter

REPO = Path(__file__).resolve().parents[1]
SCORE_IMAGEM_MINIMO = 0.90


def _repositorio(args) -> PostgresQuimiaRepository:
    s = Settings()
    if args.permitir_host != s.db_host:
        sys.exit(f"--permitir-host precisa ser exatamente o host configurado no .env ({s.db_host!r}); recebi {args.permitir_host!r}")
    return PostgresQuimiaRepository(
        host=s.db_host, port=s.db_port, dbname=s.db_name, user=s.db_user, password=s.db_password,
        sslmode=s.db_sslmode, allow_remote_host=args.permitir_host,
    )


def _registro_fora_do_repo(caminho: Path) -> Path:
    caminho = caminho.resolve()
    if REPO in caminho.parents:
        sys.exit(f"o registro de reversão tem ids do banco e não pode ficar dentro do repo: {caminho}")
    return caminho


def _itens(args) -> list[dict]:
    avaliacao = {x["source_id"]: x for x in json.loads(Path(args.avaliacao).read_text(encoding="utf-8"))}
    itens = []
    with open(args.aprovados, encoding="utf-8-sig", newline="") as fh:
        for linha in csv.DictReader(fh):
            if linha["aprovado"].strip().lower() != "sim":
                continue
            a = avaliacao[linha["source_id"]]
            raw = json.loads(Path(a["cache"]).read_text(encoding="utf-8"))
            motivos = motivos_exclusao(raw)  # reavalia: o CSV aprova o nome, não substitui o critério
            score = (a.get("imagem") or {}).get("score", 0)
            if motivos or score < SCORE_IMAGEM_MINIMO:
                sys.exit(f"RECUSADO {linha['nome_final']!r}: {motivos or f'imagem oficial {score} < {SCORE_IMAGEM_MINIMO}'}")
            data = a["data_atualizacao"]
            itens.append({
                "marca": linha["marca"], "nome": linha["nome_final"], "versao": a["versao"],
                "tipo_produto": (linha.get("tipo_produto") or "outro").strip(),
                "data_atualizacao": date.fromisoformat(data) if data else None,
                "fonte_url": a["fonte_url"], "raw_json": raw,
            })
    return itens


def _plano(repo, itens: list[dict]) -> None:
    with repo._connect() as conn, conn.cursor() as cur:
        for i in itens:
            cur.execute("SELECT id FROM marca WHERE lower(nome)=lower(%s)", (i["marca"],))
            marca = cur.fetchone()
            produto = None
            if marca:
                cur.execute("SELECT id FROM produto WHERE id_marca=%s AND lower(nome)=lower(%s)", (marca[0], i["nome"]))
                produto = cur.fetchone()
            cur.execute("SELECT id FROM fds WHERE fonte_url=%s", (i["fonte_url"],))
            fds = cur.fetchone()
            print(f"  {i['marca']} | {i['nome']} | v{i['versao']} -> marca {'existe' if marca else 'NOVA'}, "
                  f"produto {'existe' if produto else 'NOVO'}, FDS {'JÁ EXISTE (será ignorada)' if fds else 'nova'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("acao", choices=("carregar", "reverter"))
    p.add_argument("--permitir-host", required=True)
    p.add_argument("--registro", required=True, type=Path)
    p.add_argument("--aprovados", type=Path)
    p.add_argument("--avaliacao", type=Path)
    p.add_argument("--executar", action="store_true", help="sem isto, só mostra o plano")
    args = p.parse_args()
    registro_path = _registro_fora_do_repo(args.registro)
    repo = _repositorio(args)

    if args.acao == "carregar":
        if not (args.aprovados and args.avaliacao):
            sys.exit("carregar exige --aprovados e --avaliacao")
        if registro_path.exists():
            sys.exit(f"já existe um registro em {registro_path}: reverta ou mova antes de uma nova carga")
        itens = _itens(args)
        print(f"{len(itens)} itens ({'EXECUÇÃO' if args.executar else 'plano, nada será gravado'}):")
        _plano(repo, itens)
        if not args.executar:
            return
        registro = carregar(repo, itens, TABELAS_DA_CARGA)
        registro["banco"] = Settings().db_name
        registro_path.parent.mkdir(parents=True, exist_ok=True)
        registro_path.write_text(json.dumps(registro, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        print("criado:", {k: len(v) for k, v in registro["criado"].items()}, "| resultados:", [i["resultado"] for i in registro["itens"]])
        if registro["substancia_nova_alerta"]:
            print("ATENÇÃO: surgiram substâncias novas (não serão apagadas pela reversão):", registro["substancia_nova_alerta"])
        print("registro de reversão:", registro_path)
    else:
        registro = json.loads(registro_path.read_text(encoding="utf-8"))
        print("reverteria:", {k: len(v) for k, v in registro["criado"].items()})
        if not args.executar:
            return
        diferencas = reverter(repo, registro)
        print("REVERSÃO OK: tabelas da carga idênticas ao estado anterior (exceto a trilha de auditoria)" if not diferencas
              else f"DIFERENÇAS: {json.dumps(diferencas, indent=1)}")


if __name__ == "__main__":
    main()
