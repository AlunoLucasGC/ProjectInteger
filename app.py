"""Aplicação Flask do MVP Feira Fácil.

Este arquivo concentra o backend principal da aplicação:
- configura o Flask;
- conversa com o banco SQLite;
- controla login e permissões;
- processa fichas com OCR;
- busca imagens no Unsplash;
- cadastra, atualiza e exclui produtos.

A ideia dos comentários abaixo é servir também como material de estudo.
"""

# Permite usar anotações de tipos modernas, como "str | None",
# mesmo em situações em que o Python ainda precisa adiar a avaliação
# dessas anotações.
from __future__ import annotations

# =========================
# BIBLIOTECAS UTILIZADAS
# =========================

# "os" permite acessar variáveis de ambiente, como a chave do Unsplash.
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

# Carrega as informações do arquivo .env para as variáveis de ambiente.
# Ex.: UNSPLASH_ACCESS_KEY, SECRET_KEY, ADMIN_EMAIL etc.
load_dotenv()

# =========================
# CONFIGURAÇÕES DO PROJETO
# =========================

# Pasta onde este app.py está localizado.
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
IMAGE_DEFAULT_TIMEOUT: Final = 10
IMAGE_MIN_SCORE: Final = 35
IMAGE_FALLBACK_URL: Final = ""

# Traduções usadas nas buscas do Unsplash.
# O usuário pode digitar "tomate", enquanto o Unsplash pode ter
# resultados melhores para "tomato".
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
# Palavras que indicam que a foto pode representar outra coisa.
# Ex.: para "tomate", "pizza" e "sauce" diminuem a pontuação.
NEGATIVE_TERMS: Final = {
    "banana": {"coffee", "cafe", "espresso", "latte", "cup", "breakfast", "cake", "bread", "smoothie"},
    "tomate": {"pizza", "sauce", "salad", "burger", "hamburger", "sandwich"},
    "maca": {"pie", "cake", "juice", "salad", "dessert"},
    "laranja": {"juice", "cocktail", "drink", "cake"},
    "batata": {"fries", "french", "burger", "hamburger", "chips"},
}


# =========================
# BANCO DE DADOS
# =========================

# Abre uma conexão com o banco SQLite.
# A função é usada sempre que precisamos consultar ou alterar dados.
def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE)
        # Permite acessar cada coluna pelo nome, por exemplo: user["email"].
    connection.row_factory = sqlite3.Row
        # Faz o SQLite respeitar as relações entre as tabelas.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


# Cria as tabelas do banco (caso ainda não existam), garante a categoria
# padrão, executa a migração de dados antigos e cria o administrador
# definido no .env, se essas credenciais estiverem configuradas.
def init_database() -> None:
    with get_connection() as connection:
                # Lê o database.sql e executa sua estrutura no SQLite.
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


# Cria um usuário administrador inicial usando ADMIN_EMAIL e ADMIN_PASSWORD.
# Se essas variáveis não existirem no .env, nenhuma conta de administrador
# é criada automaticamente.
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


# Converte produtos do modelo antigo da aplicação para a tabela atual.
# Isso evita perder dados quando a estrutura do banco evolui.
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
                # INSERT adiciona o novo produto ao banco.
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


# Verifica se o arquivo enviado possui uma extensão de imagem permitida.
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Verifica se um documento possui uma extensão permitida.
# Atualmente essa função fica preparada para documentos, embora o cadastro
# de documentos tenha sido desativado no fluxo atual.
def allowed_document(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in DOCUMENT_EXTENSIONS


# Remove acentos e coloca o texto em minúsculas.
# Ex.: "Maçãs" -> "macas".
# Isso facilita comparar palavras digitadas em português com metadados
# que vieram do Unsplash em inglês.
def _normalizar_termo_imagem(product_name: str) -> str:
    normalized = unicodedata.normalize("NFKD", product_name.lower()).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", normalized).strip()


# Divide um texto em palavras individuais (tokens), ignorando palavras
# muito curtas. Esses tokens são usados para comparar o produto com
# título, descrição e tags das fotos.
def _tokens(texto: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", _normalizar_termo_imagem(texto))
        if len(token) >= 3
    }


# Descobre qual é o produto principal quando o nome possui mais de uma palavra.
# Ex.: "Tomates frescos" -> "tomate".
def _produto_principal(termo: str) -> str:
    """Retorna o ingrediente/produto principal para a consulta de imagens."""
    tokens = _tokens(termo)
    for token in tokens:
        if token in PHOTO_TRANSLATIONS:
            return token
    return termo


# Monta várias consultas diferentes para aumentar as chances de encontrar
# uma fotografia que realmente mostre o produto.
def _consultas_imagem(termo: str) -> list[str]:
    principal = _produto_principal(termo)
    traducao = PHOTO_TRANSLATIONS.get(principal, principal)
    consultas = [
        f"{traducao} single {traducao} isolated on white background",
        f"one {traducao} isolated",
        f"{traducao} fresh whole",
        f"{traducao} vegetable" if principal not in {"banana", "maca", "laranja", "limao", "uva", "manga", "mamao", "abacaxi", "melancia", "morango"} else f"{traducao} fruit",
    ]
    if termo != principal:
        consultas.insert(0, f"{termo} fresh produce")
    return list(dict.fromkeys(consultas))


# Calcula uma pontuação para cada foto encontrada.
# Quanto mais a foto combinar com o produto, maior a pontuação.
# Termos genéricos ou que representam outro prato/produto diminuem a nota.
def _score_imagem(foto: dict, termo: str) -> int:
    principal = _produto_principal(termo)
    traducao = PHOTO_TRANSLATIONS.get(principal, principal)
    alt = str(foto.get("alt_description") or "")
    descricao = str(foto.get("description") or "")
    tags = " ".join(
        str(tag.get("title") or "")
        for tag in foto.get("tags", [])
        if isinstance(tag, dict)
    )
    contexto = _normalizar_termo_imagem(f"{alt} {descricao} {tags}")
    tokens_contexto = _tokens(contexto)
    pontuacao = 0

    if principal in tokens_contexto:
        pontuacao += 60
    if traducao and _tokens(traducao) & tokens_contexto:
        pontuacao += 45
    if termo in contexto:
        pontuacao += 35

    palavras_bom_contexto = {
        "fresh", "produce", "vegetable", "fruit", "food", "harvest",
        "organic", "raw", "farm", "agriculture", "ingredient",
    }
    pontuacao += 5 * len(palavras_bom_contexto & tokens_contexto)

    # Evita fotos genéricas de bancas/feiras, pratos prontos e composições.
    termos_genericos = {
        "market", "stall", "stand", "display", "assortment", "variety",
        "many", "basket", "baskets", "table", "shelf", "store", "shop",
        "salad", "dish", "plate", "recipe", "cooked", "meal",
    }
    pontuacao -= 20 * len(termos_genericos & tokens_contexto)

    for negativo in NEGATIVE_TERMS.get(principal, set()):
        if negativo in tokens_contexto:
            pontuacao -= 60

    if "illustration" in tokens_contexto or "logo" in tokens_contexto or "drawing" in tokens_contexto:
        pontuacao -= 40

    # O nome nem sempre aparece nos metadados do Unsplash, mesmo quando
    # o produto está realmente visível. Por isso não rejeitamos automaticamente
    # uma foto apenas por falta do termo; as consultas específicas + penalidades
    # negativas fazem a seleção.
    if principal in PHOTO_TRANSLATIONS and principal not in tokens_contexto and traducao not in tokens_contexto:
        pontuacao -= 15

    return pontuacao


# Consulta a API do Unsplash e retorna até "limite" URLs de imagens.
# A função faz várias pesquisas e ordena os candidatos pela pontuação.
def buscar_fotos_produto(product_name: str, limite: int = 3) -> list[str]:
    """Busca até três fotos diferentes e suficientemente precisas para o produto."""
    termo = _normalizar_termo_imagem(product_name)
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
    if not termo or not access_key:
        app.logger.warning("Busca de imagens indisponível: produto ou chave ausente.")
        return []
    try:
        import requests
    except ImportError:
        app.logger.error("requests não está instalado. Execute pip install -r requirements.txt.")
        return []

    imagens: list[str] = []
    urls_vistas: set[str] = set()
    melhor_pontuacao = -1000

    for consulta in _consultas_imagem(termo):
        try:
                        # A chave da API vai no header "Authorization" no formato exigido pelo Unsplash.
            response = requests.get(
                UNSPLASH_API_URL,
                params={"query": consulta, "per_page": 30, "orientation": "squarish", "content_filter": "high"},
                headers={"Authorization": f"Client-ID {access_key}"},
                timeout=IMAGE_DEFAULT_TIMEOUT,
            )
                        # Se a API responder com erro HTTP, transforma a resposta em exceção.
            response.raise_for_status()
                        # Converte a resposta JSON em Python e pega somente a lista de fotos.
            resultados = response.json().get("results", [])
        except (requests.RequestException, ValueError, TypeError) as error:
            app.logger.warning("Falha na busca de imagem %r: %s", consulta, error)
            continue

        candidatos = []
                # Analisa cada foto retornada pela API.
        for foto in resultados:
            url = (foto.get("urls") or {}).get("regular")
            if not url or url in urls_vistas:
                continue
            pontuacao = _score_imagem(foto, termo)
            candidatos.append((pontuacao, url))

        for pontuacao, url in sorted(candidatos, reverse=True):
            if pontuacao < IMAGE_MIN_SCORE:
                continue
            imagens.append(url)
            urls_vistas.add(url)
            melhor_pontuacao = max(melhor_pontuacao, pontuacao)
            if len(imagens) >= limite:
                break
        if len(imagens) >= limite:
            break

    app.logger.info("Encontradas %s imagem(ns) para '%s'. Melhor pontuação: %s", len(imagens), product_name, melhor_pontuacao)
    return imagens


# Versão simplificada da busca: retorna apenas uma imagem.
# É útil quando precisamos de um único fallback.
def buscar_foto_produto(product_name: str) -> str | None:
    imagens = buscar_fotos_produto(product_name, limite=1)
    return imagens[0] if imagens else None


# Prepara a imagem da ficha para o OCR.
# A imagem é convertida para tons de cinza, ampliada, suavizada e
# transformada em preto e branco para facilitar a leitura dos textos.
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
# Cria o leitor do EasyOCR somente uma vez e guarda o resultado em cache.
# Isso evita carregar o modelo de OCR novamente a cada cadastro.
@lru_cache(maxsize=1)
def get_ocr_reader():
    try:
        import easyocr
    except ImportError as error:
        raise RuntimeError(
            "OCR indisponível. Instale as dependências com pip install -r requirements.txt."
        ) from error
    return easyocr.Reader(["pt"], gpu=False)


# Corrige alguns erros comuns do OCR.
# OCR pode confundir "O" com "0", "S" com "5" etc.
def corrigir_ocr(texto: str) -> str:
    texto = texto.upper()
    texto = texto.replace("T0MATE", "TOMATE").replace("T0MATO", "TOMATO")
    texto = re.sub(r"R\s*[S5]\b", "R$", texto)
    texto = re.sub(r"R\s*\$", "R$", texto)
    return texto.replace(",", ".")


# Remove espaços extras e caracteres desnecessários no começo/fim do texto.
def _limpar_valor(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip(" \t\r\n:;,.-_|/")


# Converte diferentes formatos de preço para o padrão usado no banco.
# Exemplos: "9,99" -> "9.99" e "R$ 9,99" -> "9.99".
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


# Procura no texto reconhecido pelo OCR um trecho que pareça ser um preço.
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


# Transforma o texto bruto do OCR em um dicionário organizado,
# contendo produto, quantidade, unidade e preço.
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


# Executa todo o processo de OCR: carrega o leitor, prepara a imagem,
# lê os textos e organiza os dados encontrados.
def extract_data_from_image(caminho: Path) -> tuple[dict[str, str], str]:
    inicio = perf_counter()
    leitor = get_ocr_reader()
    imagem = melhorar_imagem(caminho)
    textos = leitor.readtext(imagem, detail=0, paragraph=True)
    texto = "\n".join(textos)
    app.logger.info("OCR concluído em %.2f s", perf_counter() - inicio)
    return organizar_produto(texto), texto


# Valida os dados antes de permitir que um produto seja salvo no banco.
# Essa validação é importante mesmo que o formulário HTML já tenha regras,
# porque o usuário pode enviar dados diretamente para a rota HTTP.
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


# =========================
# CRIAÇÃO DA APLICAÇÃO FLASK
# =========================

# Cria o objeto principal da aplicação.
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao"),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
)
# Garante que as pastas necessárias existam antes de receber arquivos.
UPLOAD_FOLDER.mkdir(exist_ok=True)
DOCUMENT_FOLDER.mkdir(parents=True, exist_ok=True)
init_database()


# =========================
# USUÁRIO E AUTENTICAÇÃO
# =========================

# Procura no banco o usuário atualmente logado.
# O ID do usuário fica guardado na sessão do navegador.
def current_user():
        # Recupera da sessão o ID salvo no momento do login.
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


# Disponibiliza o usuário atual automaticamente para os templates Jinja.
# Assim os arquivos HTML podem usar "current_user" sem precisar recebê-lo
# manualmente em cada render_template().
@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# Decorator que protege páginas que exigem apenas um usuário logado.
def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            flash("Faça login para continuar.", "error")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


# Decorator que protege páginas exclusivas para produtores.
# Primeiro verifica se existe login; depois verifica o tipo da conta.
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
        return view(*args, **kwargs)

    return wrapped


# Decorator que protege páginas exclusivas para administradores.
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


# =========================
# ROTAS PÚBLICAS
# =========================

# Página inicial: lista produtos disponíveis e permite pesquisar
# pelo nome do produto ou pelo nome do produtor.
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


# Mostra os detalhes de um produto específico.
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


# Mostra o perfil público de um produtor e os produtos disponíveis dele.
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


# Entrega imagens locais usadas no catálogo.
# Arquivos dentro de "documentos/" não são disponibilizados publicamente.
@app.get("/uploads/<path:nome>")
def upload(nome: str):
    # Somente arquivos de imagem do catálogo ficam acessíveis por esta rota.
    if nome.startswith("documentos/"):
        return redirect(url_for("pagina_inicial"))
    return send_from_directory(UPLOAD_FOLDER, nome)


# =========================
# LOGIN E CADASTRO
# =========================

# GET: mostra a tela de login.
# POST: recebe e-mail e senha, verifica a conta e cria a sessão.
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
        # Remove qualquer sessão anterior antes de iniciar uma nova.
    session.clear()
        # Guarda somente o ID do usuário na sessão. Os demais dados continuam no banco.
    session["user_id"] = user["id_usuario"]
    next_url = request.form.get("next") or request.args.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    if user["tipo"] == "admin":
        return redirect(url_for("admin_produtores"))
    if user["tipo"] == "produtor":
            # Depois da operação, volta para o painel do produtor.
    return redirect(url_for("painel_produtor"))
    return redirect(url_for("perfil"))


# Encerra a sessão atual e volta para a página inicial.
@app.get("/logout")
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "success")
    return redirect(url_for("pagina_inicial"))


# Cadastro de consumidor ou produtor.
# A diferença é que o produtor também informa telefone/WhatsApp e cidade.
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
            status = "aprovado"
            documento_nome = None

            if tipo == "produtor":
                producer_id = connection.execute(
                    """
                    INSERT INTO tb_produtores (nome, telefone, email, cidade)
                    VALUES (?, ?, ?, ?)
                    """,
                    (nome, telefone, email, cidade),
                ).lastrowid
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
        flash("Cadastro realizado! Agora você já pode entrar como produtor.", "success")
    else:
        flash("Cadastro realizado! Agora você já pode entrar.", "success")
    return redirect(url_for("login"))


# Mostra o perfil do usuário logado.
# Para produtores, também carrega os produtos cadastrados por ele.
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


# =========================
# ÁREA DO PRODUTOR
# =========================

# Painel privado onde o produtor visualiza seu catálogo.
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


# Área administrativa para listar produtores.
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


# Permite ao administrador alterar o status de um produtor.
# Essa parte permanece no sistema para futuras necessidades administrativas.
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


# Abre a tela de cadastro/publicação de produto.
@app.get("/cadastro")
@producer_required
def cadastro():
    return render_template("cadastro.html")


# Recebe a ficha enviada pelo produtor e executa o OCR.
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
        # Salva temporariamente a ficha enviada para que o OCR possa lê-la.
    imagem.save(caminho)
    try:
                # O resultado contém os campos identificados e também o texto bruto do OCR.
        dados, texto = extract_data_from_image(caminho)
    except (RuntimeError, ValueError, OSError) as error:
        app.logger.exception("Falha ao processar imagem para OCR")
        flash(str(error), "error")
        return redirect(url_for("cadastro"))
    finally:
                # A ficha original é temporária e é apagada depois do processamento.
        caminho.unlink(missing_ok=True)
    user = current_user()
    dados["produtor"] = user["produtor_nome"]
    dados["contato"] = user["produtor_telefone"] or ""
    imagens = buscar_fotos_produto(dados["produto"]) if dados["produto"] else []
        # Mostra a tela onde o produtor pode revisar os dados e escolher a foto.
    return render_template("resultado.html", dados=dados, texto=texto, imagem="", imagens=imagens)


# Faz uma nova busca de imagens usando o nome do produto corrigido/editado
# pelo produtor na tela de revisão.
@app.post("/buscar-imagens")
@producer_required
def buscar_imagens():
    produto = request.form.get("produto", "").strip()
    if not produto:
        flash("Informe o nome do produto para buscar imagens.", "error")
        return redirect(url_for("cadastro"))
    imagens = buscar_fotos_produto(produto)
    user = current_user()
    dados = {
        "produto": produto,
        "quantidade": request.form.get("quantidade", ""),
        "unidade": request.form.get("unidade", "KG"),
        "preco": request.form.get("preco", ""),
        "descricao": request.form.get("descricao", ""),
        "produtor": user["produtor_nome"],
        "contato": user["produtor_telefone"] or "",
    }
    return render_template("resultado.html", dados=dados, texto=request.form.get("texto", ""), imagem="", imagens=imagens)


# Salva definitivamente o produto no banco.
# O produtor pode escolher uma das imagens encontradas ou, se nenhuma
# for escolhida, o sistema tenta buscar uma imagem automaticamente.
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
    # O produtor pode escolher uma imagem do Unsplash ou enviar uma foto própria.
    foto_produto = request.form.get("imagem_selecionada", "").strip()
    foto_upload = request.files.get("foto_propria")

    if foto_upload and foto_upload.filename:
        # A foto enviada pelo produtor tem prioridade sobre qualquer sugestão.
        if not allowed_file(foto_upload.filename):
            flash("A foto própria deve ser JPG, JPEG, PNG ou WEBP.", "error")
            return render_template(
                "resultado.html",
                dados=dados,
                texto=request.form.get("texto", ""),
                imagem=foto_produto,
                imagens=buscar_fotos_produto(dados["produto"]) if dados["produto"] else [],
            ), 400

        nome_seguro = secure_filename(foto_upload.filename)
        nome_unico = f"{uuid.uuid4().hex}_{nome_seguro}"
        caminho_foto = UPLOAD_FOLDER / nome_unico
        foto_upload.save(caminho_foto)
        foto_produto = nome_unico

    if not foto_produto:
        foto_produto = buscar_foto_produto(dados["produto"])
    with get_connection() as connection:
                # Todos os produtos novos começam na categoria padrão "Sem categoria".
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


# Abre a tela para trocar a imagem de um produto já publicado.
@app.post("/produtos/<int:product_id>/imagens")
@producer_required
def escolher_imagem_produto(product_id: int):
    user = current_user()
    with get_connection() as connection:
        produto = connection.execute(
            "SELECT id_produto AS id, nome, foto_produto AS imagem FROM tb_produtos WHERE id_produto = ? AND id_produtor = ?",
            (product_id, user["id_produtor"]),
        ).fetchone()
    if produto is None:
        flash("Produto não encontrado no seu catálogo.", "error")
        return redirect(url_for("painel_produtor"))
    imagens = buscar_fotos_produto(produto["nome"])
    return render_template("escolher_imagem.html", produto=produto, imagens=imagens)


# Salva a imagem escolhida pelo produtor para um produto existente.
@app.post("/produtos/<int:product_id>/imagem")
@producer_required
def atualizar_imagem_produto(product_id: int):
    user = current_user()
    imagem = request.form.get("imagem_selecionada", "").strip()
    foto_upload = request.files.get("foto_propria")

    if foto_upload and foto_upload.filename:
        if not allowed_file(foto_upload.filename):
            flash("A foto própria deve ser JPG, JPEG, PNG ou WEBP.", "error")
            return redirect(url_for("painel_produtor"))
        nome_seguro = secure_filename(foto_upload.filename)
        nome_unico = f"{uuid.uuid4().hex}_{nome_seguro}"
        caminho_foto = UPLOAD_FOLDER / nome_unico
        foto_upload.save(caminho_foto)
        imagem = nome_unico
    elif not imagem.startswith("https://images.unsplash.com/"):
        flash("Selecione uma imagem válida do Unsplash ou envie uma foto própria.", "error")
        return redirect(url_for("painel_produtor"))
    with get_connection() as connection:
        changed = connection.execute(
            "UPDATE tb_produtos SET foto_produto = ? WHERE id_produto = ? AND id_produtor = ?",
            (imagem, product_id, user["id_produtor"]),
        ).rowcount
    flash("Imagem do produto atualizada!", "success" if changed else "error")
    return redirect(url_for("painel_produtor"))


# Exclui um produto pertencente ao produtor logado.
@app.post("/produtos/<int:product_id>/excluir")
@producer_required
def excluir_produto(product_id: int):
    user = current_user()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT foto_produto FROM tb_produtos WHERE id_produto = ? AND id_produtor = ?",
            (product_id, user["id_produtor"]),
        ).fetchone()
        deleted = connection.execute(
            "DELETE FROM tb_produtos WHERE id_produto = ? AND id_produtor = ?",
            (product_id, user["id_produtor"]),
        ).rowcount
    if deleted and row and row["foto_produto"] and not str(row["foto_produto"]).startswith("http"):
        (UPLOAD_FOLDER / str(row["foto_produto"])).unlink(missing_ok=True)
    flash(
        "Produto excluído do seu catálogo." if deleted else "Produto não encontrado no seu catálogo.",
        "success" if deleted else "error",
    )
    return redirect(url_for("painel_produtor"))


# Exclui todos os produtos do catálogo do produtor logado.
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


# =========================
# INICIALIZAÇÃO
# =========================

# Este bloco só é executado quando rodamos "python app.py".
# Se o arquivo for importado por outro módulo, o servidor não é iniciado.
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
