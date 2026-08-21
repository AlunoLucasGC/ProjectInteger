"""Exibe o conteúdo do banco SQLite sem exigir o programa ``sqlite3`` instalado."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

DEFAULT_DATABASE = Path(__file__).with_name("feira_facil.db")

QUERIES = {
    "produtos": """
        SELECT p.id_produto, p.nome AS produto, p.quantidade, p.unidade, p.preco,
               pr.nome AS produtor, pr.telefone, c.nome AS categoria,
               p.disponivel, p.data_cadastro
        FROM tb_produtos AS p
        JOIN tb_produtores AS pr ON pr.id_produtor = p.id_produtor
        JOIN tb_categorias AS c ON c.id_categoria = p.id_categoria
        ORDER BY p.id_produto DESC
    """,
    "produtores": "SELECT * FROM tb_produtores ORDER BY id_produtor DESC",
    "categorias": "SELECT * FROM tb_categorias ORDER BY nome",
    "tabelas": "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name",
}


def print_rows(rows: list[sqlite3.Row]) -> None:
    """Imprime as linhas de uma consulta em formato legível no terminal."""
    if not rows:
        print("Nenhum registro encontrado.")
        return

    columns = rows[0].keys()
    widths = {
        column: max(len(column), *(len(str(row[column] if row[column] is not None else "")) for row in rows))
        for column in columns
    }
    print(" | ".join(column.ljust(widths[column]) for column in columns))
    print("-+-".join("-" * widths[column] for column in columns))
    for row in rows:
        print(" | ".join(str(row[column] if row[column] is not None else "").ljust(widths[column]) for column in columns))


def main() -> None:
    parser = argparse.ArgumentParser(description="Consulta o arquivo SQLite do Feira Fácil.")
    parser.add_argument("consulta", choices=QUERIES, nargs="?", default="produtos")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE, help="Caminho para o arquivo .db")
    args = parser.parse_args()

    if not args.database.is_file():
        parser.error(f"Banco não encontrado: {args.database}. Inicie a aplicação primeiro com 'python app.py'.")

    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        print_rows(connection.execute(QUERIES[args.consulta]).fetchall())


if __name__ == "__main__":
    main()
