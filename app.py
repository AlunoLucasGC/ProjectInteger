"""Aplicação Flask do MVP Feira Fácil.

O fluxo principal é: enviar uma ficha, extrair dados com OCR, revisar os campos e
publicar o anúncio no catálogo. O SQLite foi escolhido para manter o MVP simples.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
COMMONS_API_URL: Final = "https://commons.wikimedia.org/w/api.php"
PHOTO_CACHE_FOLDER: Final = UPLOAD_FOLDER / "catalogo"
PHOTO_FILE_PATTERN: Final = re.compile(r"[^a-z0-9]+")


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


def _photo_cache_name(product_name: str) -> str:
    """Cria um nome previsível e seguro para uma foto genérica em cache."""
    normalized = unicodedata.normalize("NFKD", product_name.lower()).encode("ascii", "ignore").decode()
    slug = PHOTO_FILE_PATTERN.sub("-", normalized).strip("-")[:60] or "produto-rural"
    return f"{slug}.jpg"


def buscar_foto_generica(product_name: str) -> str | None:
    """Baixa uma foto de produto do Wikimedia Commons, sem exigir chave de API.

    A imagem é armazenada localmente para evitar uma consulta externa a cada
    visualização do catálogo. A busca é feita só quando um nome ainda não tem
    foto em cache e falhas de rede não impedem a publicação do anúncio.
    """
    PHOTO_CACHE_FOLDER.mkdir(exist_ok=True)
    cache_name = _photo_cache_name(product_name)
    cache_path = PHOTO_CACHE_FOLDER / cache_name
    if cache_path.is_file():
        return f"catalogo/{cache_name}"

    params = urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": product_name,
            "gsrnamespace": "6",
            "gsrlimit": "5",
            "prop": "imageinfo",
            "iiprop": "url|mime",
            "iiurlwidth": "640",
            "origin": "*",
        }
    )
    try:
        api_request = Request(
            f"{COMMONS_API_URL}?{params}",
            headers={"User-Agent": "FeiraFacil/1.0 (catalogo de produtos rurais)"},
        )
        with urlopen(api_request, timeout=5) as response:
            pages = json.load(response).get("query", {}).get("pages", {}).values()
        candidates = [
            page["imageinfo"][0]
            for page in pages
            if page.get("imageinfo") and page["imageinfo"][0].get("mime") == "image/jpeg"
        ]
        if not candidates:
            return None
        image_url = candidates[0].get("thumburl") or candidates[0]["url"]
        image_request = Request(image_url, headers={"User-Agent": "FeiraFacil/1.0"})
        with urlopen(image_request, timeout=10) as response:
            image = response.read(2 * 1024 * 1024 + 1)
        if not image or len(image) > 2 * 1024 * 1024:
            return None
        cache_path.write_bytes(image)
        return f"catalogo/{cache_name}"
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return None


def melhorar_imagem(caminho: Path) -> Path:
    """Aumenta contraste e tamanho da foto para tornar o OCR mais confiável."""
    import cv2  # Importação tardia: as páginas sem OCR funcionam sem OpenCV.

    imagem = cv2.imread(str(caminho))
    if imagem is None:
        raise ValueError("Não foi possível abrir a imagem enviada.")

    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    cinza = cv2.resize(cinza, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)
    _, binaria = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    tratada = caminho.with_stem(f"{caminho.stem}_tratada")
    if not cv2.imwrite(str(tratada), binaria):
        raise ValueError("Não foi possível preparar a imagem para leitura.")
    return tratada


def corrigir_ocr(texto: str) -> str:
    """Normaliza os erros mais frequentes encontrados nas fichas padronizadas."""
    texto = texto.upper().replace("T0MATE", "TOMATE")
    texto = re.sub(r"\bRSK?\b", "R$", texto)
    return texto.replace(",", ".")


def organizar_produto(texto: str) -> dict[str, str]:
    """Extrai os quatro campos da ficha, tolerando acentos e espaços do OCR."""
    resultado = EMPTY_PRODUCT.copy()
    produto = re.search(r"PRODUTO\s*:\s*([^\n]+)", texto, re.IGNORECASE)
    quantidade = re.search(
        r"QUANTIDADE\s*:\s*(\d+(?:[.,]\d+)?)\s*(KG|G|ML|L|UN|CX|DZ|MAÇO)",
        texto,
        re.IGNORECASE,
    )
    preco = re.search(r"PRE(?:Ç|C)O\s*:\s*(?:R\$\s*)?([\d.,]+)", texto, re.IGNORECASE)

    if produto:
        resultado["produto"] = produto.group(1).strip().title()
    if quantidade:
        resultado["quantidade"] = quantidade.group(1).replace(",", ".")
        resultado["unidade"] = quantidade.group(2).upper()
    if preco:
        resultado["preco"] = preco.group(1).replace(",", ".")
    return resultado


def extract_data_from_image(caminho: Path) -> tuple[dict[str, str], str]:
    """Executa OCR e devolve os campos encontrados e o texto bruto para auditoria."""
    try:
        import easyocr
    except ImportError as error:
        raise RuntimeError("OCR indisponível. Instale as dependências com pip install -r requirements.txt.") from error

    leitor = easyocr.Reader(["pt"], gpu=False)
    textos = leitor.readtext(str(melhorar_imagem(caminho)), detail=0, paragraph=True)
    texto = "\n".join(textos)
    return organizar_produto(corrigir_ocr(texto)), texto


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
app.config.update(SECRET_KEY=os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao"), MAX_CONTENT_LENGTH=8 * 1024 * 1024)
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
    except (RuntimeError, ValueError) as error:
        flash(str(error), "error")
        return redirect(url_for("cadastro"))
    return render_template("resultado.html", dados=dados, texto=texto, imagem=caminho.name)


@app.post("/publicar")
def publicar_produto():
    """Persiste somente os dados revisados e redireciona ao catálogo público."""
    dados, errors = validate_product(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("resultado.html", dados=dados, texto=request.form.get("texto", ""), imagem=request.form.get("imagem", "")), 400

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
                request.form.get("imagem") or None,
            ),
        )
    flash("Produto publicado e disponível para consumidores!", "success")
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
