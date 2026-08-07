from flask import Flask, request, render_template
from werkzeug.utils import secure_filename
import easyocr
import os
import re

# Biblioteca responsável por manipular imagens
import cv2

# Biblioteca NumPy utilizada pelo OpenCV
import numpy as np

app = Flask(__name__)

PASTA_UPLOADS = "uploads"

os.makedirs(PASTA_UPLOADS, exist_ok=True)

leitor = easyocr.Reader(["pt"], gpu=False)

# ==================================
# MELHORA A IMAGEM ANTES DO OCR
# ==================================


def melhorar_imagem(caminho):

    # Lê a imagem do disco
    imagem = cv2.imread(caminho)

    # Verifica se a imagem foi carregada corretamente
    if imagem is None:
        raise Exception("Erro ao carregar a imagem.")

    # Converte para escala de cinza
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)

    # Aumenta um pouco o tamanho da imagem
    # Isso ajuda muito quando a letra está pequena
    cinza = cv2.resize(cinza, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

    # Remove pequenos ruídos
    cinza = cv2.GaussianBlur(cinza, (3, 3), 0)

    # Aumenta bastante o constraste
    _, binaria = cv2.threshold(cinza, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # Separa o nome do arquivo da extensão
    nome_arquivo, extensao = os.path.splitext(caminho)

    # Cria um novo nome para a imagem tratada
    caminho_novo = nome_arquivo + "_tratada" + extensao

    cv2.imwrite(caminho_novo, binaria)

    return caminho_novo


# ============================================
# Corrige alguns erros comuns do OCR
# ============================================


def corrigir_ocr(texto):

    texto = texto.upper()

    texto = texto.replace("T0MATE", "TOMATE")

    texto = texto.replace("RSK", "R$")
    texto = texto.replace("RS", "R$")

    texto = texto.replace(",", ".")

    return texto


# ============================================
# Organiza o texto reconhecido
# ============================================


# ============================================
# Organiza os dados encontrados pelo OCR
# ============================================


def organizar_produto(texto):

    # Dicionário onde serão armazenados os dados
    resultado = {"produto": "", "quantidade": "", "unidade": "", "preco": ""}

    # ----------------------------------------
    # Procura o nome do produto
    # Exemplo:
    # PRODUTO: TOMATE
    # ----------------------------------------
    produto = re.search(r"PRODUTO:\s*(.+)", texto, re.IGNORECASE)

    if produto:
        resultado["produto"] = produto.group(1).strip().title()

    # ----------------------------------------
    # Procura quantidade e unidade
    # Exemplo:
    # QUANTIDADE: 2 KG
    # ----------------------------------------
    quantidade = re.search(
        r"QUANTIDADE:\s*(\d+)\s*(KG|G|ML|L|UN|CX)", texto, re.IGNORECASE
    )

    if quantidade:
        resultado["quantidade"] = quantidade.group(1)
        resultado["unidade"] = quantidade.group(2).upper()

    # ----------------------------------------
    # Procura o preço
    # Aceita PREÇO ou PRECO
    # ----------------------------------------
    preco = re.search(
    r"PRE(?:Ç|C)O:\s*R\$?\s*([\d\.]+)",
    texto,
    re.IGNORECASE
)

    if preco:
        resultado["preco"] = preco.group(1)

    return resultado


@app.route("/")
def pagina_inicial():
    return render_template("index.html")


@app.route("/cadastro")
def cadastro():
    return render_template("cadastro.html")


@app.route("/ler", methods=["POST"])
def executar_ocr():

    # Verifica se uma imagem foi enviada
    if "imagem" not in request.files:
        return render_template("resultado.html", erro="Nenhuma imagem foi enviada.")

    imagem = request.files["imagem"]

    if imagem.filename == "":
        return render_template("resultado.html", erro="Nenhuma imagem foi selecionada.")

    nome_seguro = secure_filename(imagem.filename)

    caminho = os.path.join(PASTA_UPLOADS, nome_seguro)

    imagem.save(caminho)

    imagem_tratada = melhorar_imagem(caminho)

    print("Imagem original :", caminho)
    print("Imagem tratada  :", imagem_tratada)

    # Faz o OCR na imagem tratada
    textos_encontrados = leitor.readtext(imagem_tratada, detail=0, paragraph=True)

    texto_completo = "\n".join(textos_encontrados)

    if not texto_completo:

        return render_template(
            "resultado.html",
            erro="Nenhum texto foi reconhecido.",
            dados={"produto": "", "quantidade": "", "unidade": "", "preco": ""},
        )

    texto_corrigido = corrigir_ocr(texto_completo)

    dados = organizar_produto(texto_corrigido)

    print("\n" + "=" * 45)
    print("🥕 TEXTO ORIGINAL")
    print("=" * 45)
    print(texto_completo)

    print("\n🥕 TEXTO CORRIGIDO")
    print("=" * 45)
    print(texto_corrigido)

    print("\n🥕 DADOS ORGANIZADOS")
    print("=" * 45)
    print(dados)
    print("=" * 45)

    return render_template("resultado.html", dados=dados, texto=texto_completo)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
