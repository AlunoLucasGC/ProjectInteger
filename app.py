"""Aplicação Flask do MVP Feira Fácil.

O fluxo principal é: enviar uma ficha, extrair dados com OCR, revisar os campos e
publicar o anúncio no catálogo. O SQLite foi escolhido para manter o MVP simples.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from typing import Final
from urllib.parse import quote

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

BASE_DIR: Final = Path(__file__).resolve().parent
UPLOAD_FOLDER: Final = BASE_DIR / "uploads"
DATABASE: Final = BASE_DIR / "feira_facil.db"
SCHEMA_FILE: Final = BASE_DIR / "database.sql"
ALLOWED_EXTENSIONS: Final = {"jpg", "jpeg", "png", "webp"}
UNITS: Final = {"KG", "G", "L", "ML", "UN", "CX", "DZ", "MAÇO"}
EMPTY_PRODUCT: Final = {"produto": "", "quantidade": "", "unidade": "", "preco": ""}
PHOTO_FILE_PATTERN: Final = re.compile(r"[^a-z0-9]+")
PHOTO_SOURCE_URL: Final = "https://loremflickr.com/640/480/{tags}?lock={lock}"


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão configurada para devolver linhas nomeadas."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database() -> None:
    """Inicializa o arquivo SQLite e importa anúncios do esquema antigo uma vez."""
    with get_connection() as connection:
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        connection.execute("INSERT OR IGNORE INTO tb_categorias (nome) VALUES (?)", ("Sem categoria",))
        legacy_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'produtos'"
        ).fetchone()
        connection.execute("CREATE TABLE IF NOT EXISTS migracoes (nome TEXT PRIMARY KEY)")
        migration_done = connection.execute(
            "SELECT 1 FROM migracoes WHERE nome = ?", ("produtos_para_tb_produtos",)
        ).fetchone()
        if legacy_table and migration_done is None:
            _migrate_legacy_products(connection)
        connection.execute("INSERT OR IGNORE INTO migracoes (nome) VALUES (?)", ("produtos_para_tb_produtos",))


def _migrate_legacy_products(connection: sqlite3.Connection) -> None:
    """Converte a tabela local ``produtos`` do MVP para o esquema normalizado."""
    category_id = connection.execute(
        "SELECT id_categoria FROM tb_categorias WHERE nome = ?", ("Sem categoria",)
    ).fetchone()["id_categoria"]
    legacy_products = connection.execute("SELECT * FROM produtos ORDER BY id").fetchall()
    for product in legacy_products:
        producer = connection.execute(
            "SELECT id_produtor FROM tb_produtores WHERE nome = ? AND telefone = ?",
            (product["produtor"], product["contato"]),
        ).fetchone()
        if producer is None:
            cursor = connection.execute(
                "INSERT INTO tb_produtores (nome, telefone) VALUES (?, ?)",
                (product["produtor"], product["contato"]),
            )
            producer_id = cursor.lastrowid
        else:
            producer_id = producer["id_produtor"]
        connection.execute(
            """
            INSERT INTO tb_produtos
                (id_produtor, id_categoria, nome, quantidade, unidade, preco, foto_produto, data_cadastro)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                producer_id,
                category_id,
                product["nome"],
                product["quantidade"],
                product["unidade"],
                product["preco"],
                product["imagem"],
                product["criado_em"],
            ),
        )


def allowed_file(filename: str) -> bool:
    """Impede que arquivos que não são imagens sejam salvos no servidor."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def buscar_foto_generica(product_name: str) -> str:
    """Gera uma URL fixa de foto real do Flickr para o anúncio recém-criado."""
    normalized = unicodedata.normalize("NFKD", product_name.lower()).encode("ascii", "ignore").decode()
    slug = PHOTO_FILE_PATTERN.sub("-", normalized).strip("-")[:60] or "produto-rural"
    lock = hashlib.sha256(slug.encode()).hexdigest()[:12]
    return PHOTO_SOURCE_URL.format(tags=quote(f"{slug},food"), lock=lock)


def melhorar_imagem(caminho: Path) -> Path:
    """Prepara a imagem para OCR usando os bytes do arquivo, evitando falhas do cv2.imread.

    A leitura por bytes funciona melhor em ambientes Windows e também evita
    problemas com caminhos temporários que contenham caracteres especiais.
    """
    import cv2
    import numpy as np

    try:
        dados = np.frombuffer(caminho.read_bytes(), dtype=np.uint8)
    except OSError as error:
        raise ValueError("Não foi possível ler a imagem enviada.") from error

    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError("Não foi possível abrir a imagem enviada. Tente usar JPG, PNG ou WEBP.")

    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    cinza = cv2.resize(cinza, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)
    _, binaria = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    tratada = caminho.with_stem(f"{caminho.stem}_tratada")
    if not cv2.imwrite(str(tratada), binaria):
        raise ValueError("Não foi possível preparar a imagem para leitura.")
    return tratada


@lru_cache(maxsize=1)
def get_ocr_reader():
    """Inicializa o modelo uma única vez, evitando recarga a cada cadastro."""
    try:
        import easyocr
    except ImportError as error:
        raise RuntimeError("OCR indisponível. Instale as dependências com pip install -r requirements.txt.") from error
    return easyocr.Reader(["pt"], gpu=False)


def corrigir_ocr(texto: str) -> str:
    """Normaliza erros frequentes encontrados nas fichas padronizadas."""
    texto = texto.upper()
    texto = texto.replace("T0MATE", "TOMATE")
    texto = texto.replace("T0MATO", "TOMATO")
    texto = re.sub(r"R\s*[S5]\b", "R$", texto)
    texto = re.sub(r"R\s*\$", "R$", texto)
    return texto.replace(",", ".")


def organizar_produto(texto: str) -> dict[str, str]:
    """Extrai os campos mesmo quando a ficha não possui ':' após os rótulos."""
    resultado = EMPTY_PRODUCT.copy()
    texto = corrigir_ocr(texto)

    # Aceita tanto "PRODUTO: tomate" quanto "PRODUTO tomate".
    produto = re.search(
        r"PRODUTO\s*:?\s*(.+?)(?=\s+QUANTIDADE\b|\s+PRE(?:Ç|C)O\b|$)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    quantidade = re.search(
        r"QUANTIDADE\s*:?\s*(\d+(?:[.,]\d+)?)\s*(KG|G|ML|L|UN|CX|DZ|MAÇO)",
        texto,
        re.IGNORECASE,
    )
    preco = re.search(
        r"PRE(?:Ç|C)O\s*:?\s*(?:R\$\s*)?([\d.,]+)\s*R?\$?",
        texto,
        re.IGNORECASE,
    )

    if produto:
        resultado["produto"] = produto.group(1).strip(" :\n\t").title()
    if quantidade:
        resultado["quantidade"] = quantidade.group(1).replace(",", ".")
        resultado["unidade"] = quantidade.group(2).upper()
    if preco:
        resultado["preco"] = preco.group(1).replace(",", ".")
    return resultado


def extract_data_from_image(caminho: Path) -> tuple[dict[str, str], str]:
    """Executa OCR e devolve os campos encontrados e o texto bruto para auditoria."""
    inicio = perf_counter()
    leitor = get_ocr_reader()
    imagem_tratada = melhorar_imagem(caminho)
    try:
        textos = leitor.readtext(str(imagem_tratada), detail=0, paragraph=True)
        texto = "\n".join(textos)
        app.logger.info("OCR concluído em %.2f s", perf_counter() - inicio)
        return organizar_produto(texto), texto
    finally:
        imagem_tratada.unlink(missing_ok=True)


def validate_product(form: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Valida e normaliza o que o produtor confirmou antes de gravar no banco."""
    data = {key: form.get(key, "").strip() for key in (*EMPTY_PRODUCT, "produtor", "contato")}
    data["unidade"] = data["unidade"].upper()
    errors: list[str] = []

    if not data["produto"] or len(data["produto"]) > 100:
        errors.append("Informe um nome de produto com até 100 caracteres.")
    if not re.fullmatch(r"\d+(?:[.,]\d+)?", data["quantidade"]):
        errors.append("Informe uma quantidade numérica maior que zero.")
    elif Decimal(data["quantidade"].replace(",", ".")) <= 0:
        errors.append("A quantidade deve ser maior que zero.")
    if data["unidade"] not in UNITS:
        errors.append("Escolha uma unidade válida.")
    try:
        price = Decimal(data["preco"].replace(",", "."))
        if price < 0:
            errors.append("O preço não pode ser negativo.")
        else:
            data["preco"] = f"{price:.2f}"
    except InvalidOperation:
        errors.append("Informe um preço válido.")
    if not data["produtor"] or len(data["produtor"]) > 100:
        errors.append("Informe o nome do produtor.")
    if not data["contato"] or len(data["contato"]) > 100:
        errors.append("Informe um telefone ou WhatsApp para contato.")
    return data, errors


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao"),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
UPLOAD_FOLDER.mkdir(exist_ok=True)
init_database()


@app.get("/")
def pagina_inicial():
    """Exibe o catálogo, opcionalmente filtrado pelo texto buscado."""
    busca = request.args.get("q", "").strip()
    with get_connection() as connection:
        produtos = connection.execute(
            """
            SELECT p.id_produto AS id, p.nome, p.quantidade, p.unidade,
                   printf('%.2f', p.preco) AS preco, pr.nome AS produtor,
                   pr.telefone AS contato, p.foto_produto AS imagem
            FROM tb_produtos AS p
            JOIN tb_produtores AS pr ON pr.id_produtor = p.id_produtor
            WHERE p.disponivel = 1 AND (p.nome LIKE ? OR pr.nome LIKE ?)
            ORDER BY p.id_produto DESC
            """,
            (f"%{busca}%", f"%{busca}%"),
        ).fetchall()
    return render_template("index.html", produtos=produtos, busca=busca)


@app.get("/cadastro")
def cadastro():
    return render_template("cadastro.html")


@app.post("/ler")
def executar_ocr():
    """Salva uma foto validada, lê a ficha e abre a tela de revisão."""
    imagem: FileStorage | None = request.files.get("imagem")
    if not imagem or not imagem.filename:
        flash("Selecione uma imagem da ficha para continuar.", "error")
        return redirect(url_for("cadastro"))
    if not allowed_file(imagem.filename):
        flash("Envie uma imagem JPG, JPEG, PNG ou WEBP.", "error")
        return redirect(url_for("cadastro"))

    nome = secure_filename(imagem.filename)
    caminho = UPLOAD_FOLDER / f"{uuid.uuid4().hex}_{nome}"
    imagem.save(caminho)
    try:
        dados, texto = extract_data_from_image(caminho)
    except (RuntimeError, ValueError, OSError) as error:
        flash(str(error), "error")
        return redirect(url_for("cadastro"))
    finally:
        caminho.unlink(missing_ok=True)

    return render_template("resultado.html", dados=dados, texto=texto, imagem="")


@app.post("/publicar")
def publicar_produto():
    """Persiste somente os dados revisados e redireciona ao catálogo público."""
    dados, errors = validate_product(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template(
            "resultado.html",
            dados=dados,
            texto=request.form.get("texto", ""),
            imagem=request.form.get("imagem", ""),
        ), 400

    foto_generica = buscar_foto_generica(dados["produto"])
    with get_connection() as connection:
        category_id = connection.execute(
            "SELECT id_categoria FROM tb_categorias WHERE nome = ?", ("Sem categoria",)
        ).fetchone()["id_categoria"]
        producer = connection.execute(
            "SELECT id_produtor FROM tb_produtores WHERE nome = ? AND telefone = ?",
            (dados["produtor"], dados["contato"]),
        ).fetchone()
        if producer is None:
            producer_id = connection.execute(
                "INSERT INTO tb_produtores (nome, telefone) VALUES (?, ?)",
                (dados["produtor"], dados["contato"]),
            ).lastrowid
        else:
            producer_id = producer["id_produtor"]
        connection.execute(
            """
            INSERT INTO tb_produtos
                (id_produtor, id_categoria, nome, quantidade, unidade, preco, foto_produto, foto_ficha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                producer_id,
                category_id,
                dados["produto"],
                dados["quantidade"],
                dados["unidade"],
                dados["preco"],
                foto_generica,
                None,
            ),
        )
    flash("Produto publicado e disponível para consumidores!", "success")
    return redirect(url_for("pagina_inicial"))


@app.post("/produtos/<int:product_id>/excluir")
def excluir_produto(product_id: int):
    """Remove um anúncio do catálogo e mantém os dados de outros produtores."""
    with get_connection() as connection:
        deleted = connection.execute("DELETE FROM tb_produtos WHERE id_produto = ?", (product_id,)).rowcount
    flash("Produto excluído do catálogo." if deleted else "Produto não encontrado.", "success" if deleted else "error")
    return redirect(url_for("pagina_inicial"))


@app.get("/uploads/<path:nome>")
def upload(nome: str):
    """Entrega somente arquivos do diretório de uploads controlado pela aplicação."""
    return send_from_directory(UPLOAD_FOLDER, nome)


@app.errorhandler(413)
def arquivo_grande(_error: object):
    flash("A imagem deve ter no máximo 8 MB.", "error")
    return redirect(url_for("cadastro"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=os.environ.get("FLASK_DEBUG") == "1")
