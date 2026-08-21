"""Aplicação Flask do MVP Feira Fácil.

O fluxo principal é: enviar uma ficha, extrair dados com OCR, revisar os campos e
publicar o anúncio no catálogo. O SQLite foi escolhido para manter o MVP simples.
"""

from __future__ import annotations

import os
import re
import sqlite3
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from flask import Flask, flash, redirect, render_template, request, send_from_directory, url_for
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

BASE_DIR: Final = Path(__file__).resolve().parent
UPLOAD_FOLDER: Final = BASE_DIR / "uploads"
DATABASE: Final = BASE_DIR / "feira_facil.db"
ALLOWED_EXTENSIONS: Final = {"jpg", "jpeg", "png", "webp"}
UNITS: Final = {"KG", "G", "L", "ML", "UN", "CX", "DZ", "MAÇO"}
EMPTY_PRODUCT: Final = {"produto": "", "quantidade": "", "unidade": "", "preco": ""}


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão configurada para devolver linhas nomeadas."""
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database() -> None:
    """Cria a única tabela do MVP caso ela ainda não exista."""
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS produtos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                quantidade TEXT NOT NULL,
                unidade TEXT NOT NULL,
                preco TEXT NOT NULL,
                produtor TEXT NOT NULL,
                contato TEXT NOT NULL,
                imagem TEXT,
                criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def allowed_file(filename: str) -> bool:
    """Impede que arquivos que não são imagens sejam salvos no servidor."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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
            "SELECT * FROM produtos WHERE nome LIKE ? OR produtor LIKE ? ORDER BY id DESC",
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

    with get_connection() as connection:
        connection.execute(
            "INSERT INTO produtos (nome, quantidade, unidade, preco, produtor, contato, imagem) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (dados["produto"], dados["quantidade"], dados["unidade"], dados["preco"], dados["produtor"], dados["contato"], request.form.get("imagem") or None),
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
