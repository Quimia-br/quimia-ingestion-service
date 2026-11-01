from __future__ import annotations

from datetime import date
import json
import os
from urllib.parse import urlsplit

from quimia_ingestion.core.exceptions import ConfigurationError
from quimia_ingestion.domain.models import ProductRecord

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def non_local_db_hosts(host: str, env=os.environ) -> list[str]:
    """Destinos não locais que o libpq poderia usar. Lista vazia = destino efetivo 100% local.

    Além do host configurado, considera o que redireciona a conexão mesmo com host explícito
    (PGHOSTADDR, PGSERVICE) e DATABASE_URL (não lido pelo código; bloqueado por precaução).
    """
    hosts = [h.strip() for h in host.split(",")] if host.strip() else ["<ausente>"]
    hosts += [h.strip() for h in env.get("PGHOSTADDR", "").split(",") if h.strip()]
    if env.get("PGSERVICE"):
        hosts.append(f"PGSERVICE={env['PGSERVICE']}")
    if env.get("DATABASE_URL"):
        try:
            hosts.append(urlsplit(env["DATABASE_URL"]).hostname or "DATABASE_URL sem host")
        except ValueError:
            hosts.append("DATABASE_URL inválida")
    return [h for h in hosts if h.lower() not in LOCAL_DB_HOSTS]


def assert_local_db(host: str) -> None:
    blocked = non_local_db_hosts(host)
    if blocked:
        raise ConfigurationError(
            f"banco bloqueado: destino não local ({', '.join(blocked)}); nesta fase só localhost/127.0.0.1/::1"
        )


class PostgresQuimiaRepository:
    """Adapter fino para o schema atual do quimia-bd. Importa psycopg apenas em runtime."""

    def __init__(self, *, host: str, port: int, dbname: str, user: str, password: str, sslmode: str = "require"):
        # Antes de importar/conectar: nenhum caminho (CLI ou workflow) abre conexão remota.
        assert_local_db(host)
        try:
            import psycopg
        except ImportError as exc:
            raise ConfigurationError('instale o extra postgres: pip install ".[postgres]"') from exc
        self._psycopg = psycopg
        self.conninfo = dict(host=host, port=port, dbname=dbname, user=user, password=password, sslmode=sslmode)

    def _connect(self):
        return self._psycopg.connect(**self.conninfo)

    def find_fds_by_source_url(self, source_url: str) -> int | None:
        if not source_url:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM fds WHERE fonte_url = %s ORDER BY id DESC LIMIT 1", (source_url,))
            row = cur.fetchone()
            return row[0] if row else None

    def find_fds_by_identity(self, product_id: int, version: str | None, update_date: date | None) -> int | None:
        # Sem versão e sem data, "mesmo produto" não é identidade suficiente para concluir duplicidade.
        if version is None and update_date is None:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM fds
                 WHERE id_produto = %s
                   AND versao IS NOT DISTINCT FROM %s
                   AND data_atualizacao IS NOT DISTINCT FROM %s
                 ORDER BY id DESC LIMIT 1
                """,
                (product_id, version, update_date),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_or_create_product(self, brand: str, product_name: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM marca WHERE lower(nome) = lower(%s) LIMIT 1", (brand,))
            row = cur.fetchone()
            if row:
                brand_id = row[0]
            else:
                cur.execute("INSERT INTO marca (nome) VALUES (%s) RETURNING id", (brand,))
                brand_id = cur.fetchone()[0]

            cur.execute(
                "SELECT id FROM produto WHERE id_marca = %s AND lower(nome) = lower(%s) LIMIT 1",
                (brand_id, product_name),
            )
            row = cur.fetchone()
            if row:
                return row[0]
            cur.execute(
                "INSERT INTO produto (id_marca, nome, tipo_produto, descricao) VALUES (%s, %s, %s, %s) RETURNING id",
                (brand_id, product_name, "outro", "Importado automaticamente a partir de FDS."),
            )
            return cur.fetchone()[0]

    def insert_fds(self, product_id: int, version: str | None, update_date: date | None, source_url: str, raw_json: dict) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO fds (id_produto, versao, data_atualizacao, fonte_url, raw_json)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                RETURNING id
                """,
                (product_id, version, update_date, source_url, json.dumps(raw_json, ensure_ascii=False)),
            )
            return cur.fetchone()[0]

    def list_products_without_image(self) -> list[ProductRecord]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, m.nome, p.nome, p.tipo_produto, p.descricao, p.foto_url
                  FROM produto p
                  JOIN marca m ON m.id = p.id_marca
                 WHERE p.foto_url IS NULL OR btrim(p.foto_url) = ''
                 ORDER BY p.id
                """
            )
            return [ProductRecord(id=r[0], brand=r[1], name=r[2], tipo_produto=r[3], descricao=r[4], foto_url=r[5]) for r in cur.fetchall()]
