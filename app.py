from flask import Flask, request, render_template
from werkzeug.utils import secure_filename
import easyocr
import os
import re

app = Flask(__name__)

PASTA_UPLOADS = "uploads"

os.makedirs(PASTA_UPLOADS, exist_ok=True)

leitor = easyocr.Reader(["pt"], gpu=False)


# ============================================
# Corrige alguns erros comuns do OCR
# ============================================


def corrigir_ocr(texto):

    texto = texto.replace("k9", "kg")
    texto = texto.replace("K9", "kg")

    texto = texto.replace("O", "0")
    texto = texto.replace("o", "0")

    texto = texto.replace(",", ".")

    return texto


# ============================================
# Organiza o texto reconhecido
# ============================================


def organizar_produto(texto):

    palavras = texto.split()

    produto = []
    quantidade = ""
    unidade = ""
    preco = ""

    unidades = ["kg", "g", "un", "cx", "litro", "l", "ml"]

    for palavra in palavras:

        palavra_limpa = palavra.lower()

        # Unidade
        if palavra_limpa in unidades:
            unidade = palavra

        # Número inteiro (quantidade)
        elif re.fullmatch(r"\d+", palavra):
            if quantidade == "":
                quantidade = palavra

        # Número decimal (preço)
        elif re.fullmatch(r"\d+\.\d+", palavra):
            preco = palavra

        # Produto
        else:
            produto.append(palavra)

    return {
        "produto": " ".join(produto),
        "quantidade": quantidade,
        "unidade": unidade,
        "preco": preco,
    }


@app.route("/")
def pagina_inicial():
    return render_template("index.html")


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

    textos_encontrados = leitor.readtext(caminho, detail=0, paragraph=True)

    texto_completo = "\n".join(textos_encontrados)

    if not texto_completo:

        return render_template("resultado.html", erro="Nenhum texto foi reconhecido.")

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
