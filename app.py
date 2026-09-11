"""Aplicação Flask do MVP Feira Fácil."""

from __future__ import annotations

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

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.datastructures import FileStorage
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

BASE_DIR: Final = Path(__file__).resolve().parent
UPLOAD_FOLDER: Final = BASE_DIR / "uploads"
DOCUMENT_FOLDER: Final = UPLOAD_FOLDER / "documentos"
DATABASE: Final = BASE_DIR / "feira_facil.db"
SCHEMA_FILE: Final = BASE_DIR / "database.sql"
ALLOWED_EXTENSIONS: Final = {"jpg", "jpeg", "png", "webp"}
DOCUMENT_EXTENSIONS: Final = {"jpg", "jpeg", "png", "webp", "pdf"}
UNITS: Final = {"KG", "G", "L", "ML", "UN", "CX", "DZ", "MAÇO"}
EMPTY_PRODUCT: Final = {"produto": "", "descricao": "", "quantidade": "", "unidade": "", "preco": ""}
UNSPLASH_API_URL: Final = "https://api.unsplash.com/search/photos"

PHOTO_TRANSLATIONS: Final = {
    "tomate": "tomato", "tomates": "tomato", "banana": "banana", "bananas": "banana",
    "melancia": "watermelon", "melancias": "watermelon", "morango": "strawberry", "morangos": "strawberry",
    "batata": "potato", "batatas": "potato", "cenoura": "carrot", "cenouras": "carrot",
    "cebola": "onion", "cebolas": "onion", "alface": "lettuce", "alfaces": "lettuce",
    "pepino": "cucumber", "pepinos": "cucumber", "abacaxi": "pineapple", "abacaxis": "pineapple",
    "maca": "apple", "macas": "apple", "laranja": "orange", "laranjas": "orange",
    "limao": "lemon", "limoes": "lemon", "uva": "grape", "uvas": "grape",
    "mamao": "papaya", "mamaos": "papaya", "manga": "mango", "mangas": "mango",
    "pimentao": "bell pepper", "pimentoes": "bell pepper",
}
NEGATIVE_TERMS: Final = {
    "banana": {"coffee", "cafe", "espresso", "latte", "cup", "breakfast", "cake", "bread", "smoothie"},
    "tomate": {"pizza", "sauce", "salad", "burger", "hamburger", "sandwich"},
    "maca": {"pie", "cake", "juice", "salad", "dessert"},
    "laranja": {"juice", "cocktail", "drink", "cake"},
    "batata": {"fries", "french", "burger", "hamburger", "chips"},
}


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_database() -> None:
    with get_connection() as connection:
        connection.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        connection.execute("INSERT OR IGNORE INTO tb_categorias (nome) VALUES (?)", ("Sem categoria",))
        connection.execute("CREATE TABLE IF NOT EXISTS migracoes (nome TEXT PRIMARY KEY)")
        legacy_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'produtos'"
        ).fetchone()
        migration_done = connection.execute(
            "SELECT 1 FROM migracoes WHERE nome = ?", ("produtos_para_tb_produtos",)
        ).fetchone()
        if legacy_table and migration_done is None:
            _migrate_legacy_products(connection)
        connection.execute(
            "INSERT OR IGNORE INTO migracoes (nome) VALUES (?)",
            ("produtos_para_tb_produtos",),
        )
        _seed_admin(connection)


def _seed_admin(connection: sqlite3.Connection) -> None:
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not email or not password:
        return
    existing = connection.execute(
        "SELECT id_usuario FROM tb_usuarios WHERE lower(email) = ?", (email,)
    ).fetchone()
    if existing is None:
        connection.execute(
            """
            INSERT INTO tb_usuarios (nome, email, senha_hash, tipo, status)
            VALUES (?, ?, ?, 'admin', 'aprovado')
            """,
            ("Administrador", email, generate_password_hash(password)),
        )


def _migrate_legacy_products(connection: sqlite3.Connection) -> None:
    category = connection.execute(
        "SELECT id_categoria FROM tb_categorias WHERE nome = ?", ("Sem categoria",)
    ).fetchone()
    if category is None:
        return
    legacy_products = connection.execute("SELECT * FROM produtos ORDER BY id").fetchall()
    for product in legacy_products:
        producer = connection.execute(
            "SELECT id_produtor FROM tb_produtores WHERE nome = ? AND telefone = ?",
            (product["produtor"], product["contato"]),
        ).fetchone()
        if producer is None:
            producer_id = connection.execute(
                "INSERT INTO tb_produtores (nome, telefone) VALUES (?, ?)",
                (product["produtor"], product["contato"]),
            ).lastrowid
        else:
            producer_id = producer["id_produtor"]
        connection.execute(
            """
            INSERT INTO tb_produtos
            (id_produtor, id_categoria, nome, descricao, quantidade, unidade, preco, foto_produto, data_cadastro)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                producer_id,
                category["id_categoria"],
                product["nome"],
                None,
                product["quantidade"],
                product["unidade"],
                product["preco"],
                product["imagem"],
                product["criado_em"],
            ),
        )


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_document(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in DOCUMENT_EXTENSIONS


def _normalizar_termo_imagem(product_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", product_name.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", normalized).strip()


def _tokens(texto: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _normalizar_termo_imagem(texto))
        if len(token) >= 3
    }


def buscar_foto_produto(product_name: str) -> str | None:
    """Busca uma imagem do próprio produto e rejeita composições pouco relevantes."""
    termo = _normalizar_termo_imagem(product_name)
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    if not termo or not access_key:
        app.logger.warning("Busca de imagem indisponível: produto ou chave ausente.")
        return None
    try:
        import requests
    except ImportError:
        app.logger.error("requests não está instalado. Execute pip install -r requirements.txt.")
        return None

    tokens_produto = _tokens(termo)
    traducoes = [PHOTO_TRANSLATIONS[token] for token in tokens_produto if token in PHOTO_TRANSLATIONS]
    consultas = [f'"{termo}" isolated', f'"{termo}" fresh', termo]
    consultas.extend(f'"{traducao}" isolated' for traducao in traducoes)
    consultas.extend(f'"{traducao}" fresh' for traducao in traducoes)

    melhor_url: str | None = None
    melhor_pontuacao = -999

    for consulta in consultas:
        try:
            response = requests.get(
                UNSPLASH_API_URL,
                params={
                    "query": consulta,
                    "per_page": 30,
                    "orientation": "squarish",
                    "content_filter": "high",
                },
                headers={"Authorization": f"Client-ID {access_key}"},
                timeout=10,
            )
            response.raise_for_status()
            resultados = response.json().get("results", [])
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.warning("Falha na busca de imagem %r: %s", consulta, error)
            continue

        for foto in resultados:
            alt = str(foto.get("alt_description") or "")
            descricao = str(foto.get("description") or "")
            tags = " ".join(
                str(tag.get("title") or "")
                for tag in foto.get("tags", [])
                if isinstance(tag, dict)
            )
            contexto = f"{alt} {descricao} {tags}"
            tokens_contexto = _tokens(contexto)
            pontuacao = len(tokens_produto & tokens_contexto) * 20
            for traducao in traducoes:
                if _tokens(traducao) & tokens_contexto:
                    pontuacao += 30
            if termo in _normalizar_termo_imagem(f"{alt} {descricao}"):
                pontuacao += 25
            if "isolated" in tokens_contexto:
                pontuacao += 20
            if "fresh" in tokens_contexto:
                pontuacao += 5
            for negativo in NEGATIVE_TERMS.get(termo, set()):
                if negativo in tokens_contexto or negativo in contexto:
                    pontuacao -= 35
            if not alt and not descricao and not tags:
                pontuacao -= 15

            url = (foto.get("urls") or {}).get("regular")
            if url and pontuacao > melhor_pontuacao:
                melhor_pontuacao = pontuacao
                melhor_url = url

    if melhor_url and melhor_pontuacao >= 20:
        return melhor_url
    return None


def melhorar_imagem(caminho: Path):
    import cv2
    import numpy as np

    try:
        dados = np.frombuffer(caminho.read_bytes(), dtype=np.uint8)
    except OSError as error:
        raise ValueError("Não foi possível ler a imagem enviada.") from error
    if dados.size == 0:
        raise ValueError("A imagem enviada está vazia ou inválida.")
    imagem = cv2.imdecode(dados, cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError("Não foi possível abrir a imagem enviada. Tente usar JPG, PNG ou WEBP.")
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    cinza = cv2.resize(cinza, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)
    _, binaria = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binaria


@lru_cache(maxsize=1)
def get_ocr_reader():
    try:
        import easyocr
    except ImportError as error:
        raise RuntimeError(
            "OCR indisponível. Instale as dependências com pip install -r requirements.txt."
        ) from error
    return easyocr.Reader(["pt"], gpu=False)


def corrigir_ocr(texto: str) -> str:
    texto = texto.upper()
    texto = texto.replace("T0MATE", "TOMATE").replace("T0MATO", "TOMATO")
    texto = re.sub(r"R\s*[S5]\b", "R$", texto)
    texto = re.sub(r"R\s*\$", "R$", texto)
    return texto.replace(",", ".")


def _limpar_valor(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip(" \t\r\n:;,.-_|/")


def _normalizar_preco(valor: str) -> str:
    valor = valor.upper().strip()
    valor = re.sub(r"\s*R\s*\$?", "", valor)
    valor = re.sub(r"[^0-9.,]", "", valor)
    if not valor:
        return ""
    if "," in valor:
        valor = valor.replace(".", "").replace(",", ".")
    elif valor.count(".") > 1:
        partes = valor.split(".")
        valor = "".join(partes[:-1]) + "." + partes[-1]
    try:
        return f"{Decimal(valor):.2f}"
    except InvalidOperation:
        return ""


def _extrair_preco(texto: str) -> str:
    padroes = [
        r"\bPRE(?:Ç|C)O\s*:?\s*(?:R\s*\$\s*)?([0-9OQ]+(?:[.,][0-9OQ]+)?)(?:\s*R\s*\$?)?\b",
        r"\bPRE(?:Ç|C)O\s*:?\s*(?:R\s*\$\s*)?([0-9OQ]+)[OQ](?:\s*R\s*\$?)?\b",
    ]
    for padrao in padroes:
        encontrado = re.search(padrao, texto, re.IGNORECASE)
        if not encontrado:
            continue
        bruto = encontrado.group(1).upper().replace("O", "0").replace("Q", "0")
        preco = _normalizar_preco(bruto)
        if preco:
            return preco
    return ""


def organizar_produto(texto: str) -> dict[str, str]:
    resultado = EMPTY_PRODUCT.copy()
    texto = corrigir_ocr(texto)
    produto = re.search(
        r"\bPRODUTO\s*:?\s*(.+?)(?=\s+QUANTIDADE\b|\s+PRE(?:Ç|C)O\b|$)",
        texto,
        re.IGNORECASE | re.DOTALL,
    )
    quantidade = re.search(
        r"\bQUANTIDADE\s*:?\s*(\d+(?:[.,]\d+)?)\s*(KG|G|ML|L|UN|CX|DZ|MAÇO)\b",
        texto,
        re.IGNORECASE,
    )
    if produto:
        resultado["produto"] = _limpar_valor(produto.group(1)).title()
    if quantidade:
        resultado["quantidade"] = quantidade.group(1).replace(",", ".")
        resultado["unidade"] = quantidade.group(2).upper()
    resultado["preco"] = _extrair_preco(texto)
    return resultado


def extract_data_from_image(caminho: Path) -> tuple[dict[str, str], str]:
    inicio = perf_counter()
    leitor = get_ocr_reader()
    imagem = melhorar_imagem(caminho)
    textos = leitor.readtext(imagem, detail=0, paragraph=True)
    texto = "\n".join(textos)
    app.logger.info("OCR concluído em %.2f s", perf_counter() - inicio)
    return organizar_produto(texto), texto


def validate_product(form: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    data = {key: form.get(key, "").strip() for key in EMPTY_PRODUCT}
    data["unidade"] = data["unidade"].upper()
    errors: list[str] = []
    if not data["produto"] or len(data["produto"]) > 100:
        errors.append("Informe um nome de produto com até 100 caracteres.")
    if len(data["descricao"]) > 500:
        errors.append("A descrição deve ter até 500 caracteres.")
    try:
        quantity = Decimal(data["quantidade"].replace(",", "."))
        if quantity <= 0:
            errors.append("A quantidade deve ser maior que zero.")
    except (InvalidOperation, ValueError):
        errors.append("Informe uma quantidade numérica maior que zero.")
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
    return data, errors


app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao"),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
UPLOAD_FOLDER.mkdir(exist_ok=True)
DOCUMENT_FOLDER.mkdir(parents=True, exist_ok=True)
init_database()


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    with get_connection() as connection:
        return connection.execute(
            """
            SELECT u.*, p.nome AS produtor_nome, p.telefone AS produtor_telefone,
                   p.email AS produtor_email, p.cidade AS produtor_cidade
            FROM tb_usuarios u
            LEFT JOIN tb_produtores p ON p.id_produtor = u.id_produtor
            WHERE u.id_usuario = ?
            """,
            (user_id,),
        ).fetchone()


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Faça login para continuar.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def producer_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Faça login como produtor para continuar.", "error")
            return redirect(url_for("login", next=request.path))
        if user["tipo"] != "produtor":
            flash("Esta área é exclusiva para produtores.", "error")
            return redirect(url_for("pagina_inicial"))
        if user["status"] != "aprovado":
            flash("Seu cadastro de produtor ainda não foi aprovado.", "error")
            return redirect(url_for("perfil"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None or user["tipo"] != "admin":
            flash("Acesso restrito ao administrador.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.get("/")
def pagina_inicial():
    busca = request.args.get("q", "").strip()
    producer_id = request.args.get("produtor", type=int)
    sql = """
        SELECT p.id_produto AS id, p.nome, p.quantidade, p.unidade,
               printf('%.2f', p.preco) AS preco, p.descricao,
               pr.nome AS produtor, pr.id_produtor AS produtor_id,
               pr.telefone AS contato, p.foto_produto AS imagem
        FROM tb_produtos AS p
        JOIN tb_produtores AS pr ON pr.id_produtor = p.id_produtor
        WHERE p.disponivel = 1
          AND (p.nome LIKE ? OR pr.nome LIKE ?)
    """
    params: list[object] = [f"%{busca}%", f"%{busca}%"]
    if producer_id:
        sql += " AND p.id_produtor = ?"
        params.append(producer_id)
    sql += " ORDER BY p.id_produto DESC"
    with get_connection() as connection:
        produtos = connection.execute(sql, params).fetchall()
        produtor_filtro = None
        if producer_id:
            produtor_filtro = connection.execute(
                "SELECT id_produtor, nome, cidade FROM tb_produtores WHERE id_produtor = ?",
                (producer_id,),
            ).fetchone()
    return render_template(
        "index.html",
        produtos=produtos,
        busca=busca,
        produtor_filtro=produtor_filtro,
    )


@app.get("/produto/<int:product_id>")
def detalhes_produto(product_id: int):
    with get_connection() as connection:
        produto = connection.execute(
            """
            SELECT p.id_produto AS id, p.nome, p.quantidade, p.unidade,
                   printf('%.2f', p.preco) AS preco, p.descricao,
                   p.foto_produto AS imagem, pr.nome AS produtor,
                   pr.id_produtor AS produtor_id, pr.telefone AS contato,
                   pr.email AS produtor_email, pr.cidade AS cidade
            FROM tb_produtos AS p
            JOIN tb_produtores AS pr ON pr.id_produtor = p.id_produtor
            WHERE p.id_produto = ? AND p.disponivel = 1
            """,
            (product_id,),
        ).fetchone()
    if produto is None:
        flash("Produto não encontrado.", "error")
        return redirect(url_for("pagina_inicial"))
    return render_template("produto.html", produto=produto)


@app.get("/produtor/<int:producer_id>")
def perfil_produtor_publico(producer_id: int):
    with get_connection() as connection:
        produtor = connection.execute(
            """
            SELECT p.id_produtor, p.nome, p.telefone, p.email, p.cidade,
                   u.status
            FROM tb_produtores p
            LEFT JOIN tb_usuarios u ON u.id_produtor = p.id_produtor
            WHERE p.id_produtor = ?
            """,
            (producer_id,),
        ).fetchone()
        produtos = connection.execute(
            """
            SELECT p.id_produto AS id, p.nome, p.quantidade, p.unidade,
                   printf('%.2f', p.preco) AS preco, p.foto_produto AS imagem
            FROM tb_produtos p
            WHERE p.id_produtor = ? AND p.disponivel = 1
            ORDER BY p.id_produto DESC
            """,
            (producer_id,),
        ).fetchall()
    if produtor is None:
        flash("Produtor não encontrado.", "error")
        return redirect(url_for("pagina_inicial"))
    return render_template("produtor.html", produtor=produtor, produtos=produtos)


@app.get("/uploads/<path:nome>")
def upload(nome: str):
    # Somente arquivos de imagem do catálogo ficam acessíveis por esta rota.
    if nome.startswith("documentos/"):
        return redirect(url_for("pagina_inicial"))
    return send_from_directory(UPLOAD_FOLDER, nome)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("senha", "")
    with get_connection() as connection:
        user = connection.execute(
            "SELECT * FROM tb_usuarios WHERE lower(email) = ?", (email,)
        ).fetchone()
    if user is None or not check_password_hash(user["senha_hash"], password):
        flash("E-mail ou senha inválidos.", "error")
        return render_template("login.html", email=email), 401
    session.clear()
    session["user_id"] = user["id_usuario"]
    next_url = request.form.get("next") or request.args.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    if user["tipo"] == "admin":
        return redirect(url_for("admin_produtores"))
    if user["tipo"] == "produtor":
        return redirect(url_for("painel_produtor"))
    return redirect(url_for("perfil"))


@app.get("/logout")
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "success")
    return redirect(url_for("pagina_inicial"))


@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    tipo = request.args.get("tipo", request.form.get("tipo", "consumidor")).lower()
    if tipo not in {"consumidor", "produtor"}:
        tipo = "consumidor"

    if request.method == "GET":
        return render_template("registro.html", tipo=tipo)

    nome = request.form.get("nome", "").strip()
    email = request.form.get("email", "").strip().lower()
    senha = request.form.get("senha", "")
    confirmar = request.form.get("confirmar_senha", "")
    telefone = request.form.get("telefone", "").strip()
    cidade = request.form.get("cidade", "").strip()
    documento = request.files.get("documento")
    errors: list[str] = []

    if not nome or len(nome) > 100:
        errors.append("Informe seu nome com até 100 caracteres.")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        errors.append("Informe um e-mail válido.")
    if len(senha) < 6:
        errors.append("A senha deve ter pelo menos 6 caracteres.")
    if senha != confirmar:
        errors.append("As senhas não coincidem.")
    if tipo == "produtor":
        if not telefone or len(telefone) > 100:
            errors.append("Informe um telefone ou WhatsApp.")
        if not cidade or len(cidade) > 100:
            errors.append("Informe a cidade.")
        if documento is None or not documento.filename:
            errors.append("Envie um documento para análise do cadastro.")
        elif not allowed_document(documento.filename):
            errors.append("O documento deve ser JPG, PNG, WEBP ou PDF.")

    if errors:
        for error in errors:
            flash(error, "error")
        return render_template("registro.html", tipo=tipo, form=request.form), 400

    try:
        with get_connection() as connection:
            if connection.execute(
                "SELECT 1 FROM tb_usuarios WHERE lower(email) = ?", (email,)
            ).fetchone():
                flash("Este e-mail já está cadastrado.", "error")
                return render_template("registro.html", tipo=tipo, form=request.form), 409

            producer_id = None
            status = "aprovado" if tipo == "consumidor" else "pendente"
            documento_nome = None

            if tipo == "produtor":
                producer_id = connection.execute(
                    """
                    INSERT INTO tb_produtores (nome, telefone, email, cidade)
                    VALUES (?, ?, ?, ?)
                    """,
                    (nome, telefone, email, cidade),
                ).lastrowid
                original = secure_filename(documento.filename)
                documento_nome = f"{uuid.uuid4().hex}_{original}"
                documento.save(DOCUMENT_FOLDER / documento_nome)

            connection.execute(
                """
                INSERT INTO tb_usuarios
                (nome, email, senha_hash, tipo, id_produtor, status, documento)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    nome,
                    email,
                    generate_password_hash(senha),
                    tipo,
                    producer_id,
                    status,
                    documento_nome,
                ),
            )
    except sqlite3.IntegrityError:
        flash("Não foi possível concluir o cadastro. O e-mail pode já estar em uso.", "error")
        return render_template("registro.html", tipo=tipo, form=request.form), 409

    if tipo == "produtor":
        flash(
            "Cadastro enviado! Seu perfil ficará pendente até a aprovação do administrador.",
            "success",
        )
    else:
        flash("Cadastro realizado! Agora você já pode entrar.", "success")
    return redirect(url_for("login"))


@app.get("/perfil")
@login_required
def perfil():
    user = current_user()
    if user["tipo"] == "produtor":
        with get_connection() as connection:
            produtos = connection.execute(
                """
                SELECT p.id_produto AS id, p.nome, p.quantidade, p.unidade,
                       printf('%.2f', p.preco) AS preco, p.foto_produto AS imagem
                FROM tb_produtos p
                WHERE p.id_produtor = ?
                ORDER BY p.id_produto DESC
                """,
                (user["id_produtor"],),
            ).fetchall()
        return render_template("perfil.html", user=user, produtos=produtos)
    return render_template("perfil.html", user=user, produtos=[])


@app.get("/painel")
@producer_required
def painel_produtor():
    user = current_user()
    with get_connection() as connection:
        produtos = connection.execute(
            """
            SELECT p.id_produto AS id, p.nome, p.quantidade, p.unidade,
                   printf('%.2f', p.preco) AS preco, p.foto_produto AS imagem
            FROM tb_produtos p
            WHERE p.id_produtor = ?
            ORDER BY p.id_produto DESC
            """,
            (user["id_produtor"],),
        ).fetchall()
    return render_template("painel_produtor.html", user=user, produtos=produtos)


@app.get("/admin/produtores")
@admin_required
def admin_produtores():
    with get_connection() as connection:
        produtores = connection.execute(
            """
            SELECT u.id_usuario, u.nome, u.email, u.status, u.documento,
                   u.data_cadastro, p.id_produtor, p.telefone, p.cidade
            FROM tb_usuarios u
            JOIN tb_produtores p ON p.id_produtor = u.id_produtor
            WHERE u.tipo = 'produtor'
            ORDER BY
                CASE u.status WHEN 'pendente' THEN 0 WHEN 'rejeitado' THEN 1 ELSE 2 END,
                u.data_cadastro DESC
            """
        ).fetchall()
    return render_template("admin_produtores.html", produtores=produtores)


@app.post("/admin/produtores/<int:user_id>/<status>")
@admin_required
def atualizar_status_produtor(user_id: int, status: str):
    if status not in {"aprovado", "rejeitado"}:
        flash("Status inválido.", "error")
        return redirect(url_for("admin_produtores"))
    with get_connection() as connection:
        changed = connection.execute(
            """
            UPDATE tb_usuarios
            SET status = ?
            WHERE id_usuario = ? AND tipo = 'produtor'
            """,
            (status, user_id),
        ).rowcount
    flash(
        "Produtor aprovado com sucesso." if status == "aprovado" else "Produtor rejeitado.",
        "success" if changed else "error",
    )
    return redirect(url_for("admin_produtores"))


@app.get("/cadastro")
@producer_required
def cadastro():
    return render_template("cadastro.html")


@app.post("/ler")
@producer_required
def executar_ocr():
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
        app.logger.exception("Falha ao processar imagem para OCR")
        flash(str(error), "error")
        return redirect(url_for("cadastro"))
    finally:
        caminho.unlink(missing_ok=True)
    user = current_user()
    dados["produtor"] = user["produtor_nome"]
    dados["contato"] = user["produtor_telefone"] or ""
    return render_template("resultado.html", dados=dados, texto=texto, imagem="")


@app.post("/publicar")
@producer_required
def publicar_produto():
    dados, errors = validate_product(request.form)
    if errors:
        for error in errors:
            flash(error, "error")
        user = current_user()
        dados["produtor"] = user["produtor_nome"]
        dados["contato"] = user["produtor_telefone"] or ""
        return render_template(
            "resultado.html",
            dados=dados,
            texto=request.form.get("texto", ""),
            imagem=request.form.get("imagem", ""),
        ), 400

    user = current_user()
    foto_produto = buscar_foto_produto(dados["produto"])
    with get_connection() as connection:
        category_id = connection.execute(
            "SELECT id_categoria FROM tb_categorias WHERE nome = ?", ("Sem categoria",)
        ).fetchone()["id_categoria"]
        connection.execute(
            """
            INSERT INTO tb_produtos
            (id_produtor, id_categoria, nome, descricao, quantidade, unidade, preco, foto_produto, foto_ficha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id_produtor"],
                category_id,
                dados["produto"],
                dados["descricao"],
                dados["quantidade"],
                dados["unidade"],
                dados["preco"],
                foto_produto,
                None,
            ),
        )
    flash("Produto publicado e disponível para consumidores!", "success")
    return redirect(url_for("painel_produtor"))


@app.post("/produtos/<int:product_id>/excluir")
@producer_required
def excluir_produto(product_id: int):
    user = current_user()
    with get_connection() as connection:
        deleted = connection.execute(
            "DELETE FROM tb_produtos WHERE id_produto = ? AND id_produtor = ?",
            (product_id, user["id_produtor"]),
        ).rowcount
    flash(
        "Produto excluído do seu catálogo." if deleted else "Produto não encontrado no seu catálogo.",
        "success" if deleted else "error",
    )
    return redirect(url_for("painel_produtor"))


@app.post("/produtos/limpar")
@producer_required
def limpar_catalogo():
    user = current_user()
    with get_connection() as connection:
        deleted = connection.execute(
            "DELETE FROM tb_produtos WHERE id_produtor = ?",
            (user["id_produtor"],),
        ).rowcount
    flash(
        f"Catálogo limpo. {deleted} produto(s) removido(s).",
        "success",
    )
    return redirect(url_for("painel_produtor"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
