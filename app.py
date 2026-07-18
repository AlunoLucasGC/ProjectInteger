from flask import Flask, request, render_template
from werkzeug.utils import secure_filename
import easyocr
import os

app = Flask(__name__)

PASTA_UPLOADS = "uploads"

os.makedirs(PASTA_UPLOADS, exist_ok=True)

leitor = easyocr.Reader(["pt"], gpu=False)


def criar_pagina(resultado="Nenhuma imagem foi analisada."):
    return f"""
    <!DOCTYPE html>

    <html lang="pt-BR">

    <head>
        <meta charset="UTF-8">
        <meta
            name="viewport"
            content="width=device-width, initial-scale=1.0"
        >

        <title>Feira Fácil</title>

        <style>
            body{{
                margin: 0;
                padding: 30px;
                font-family: Arial, sans-serif;
                background-color: #f2f6f0;
                color: #263323;
}}

            .painel{{
                max-width: 650px;
                margin: auto;
                padding: 30px;
                background-color: white;
                border-radius: 16px;
                box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
}}

            h1{{
                margin-top: 0;
                color: #3d6b35;
}}

            .descricao{{
                line-height: 1.6;
}}

            form{{
                margin-top: 25px;
                padding: 20px;
                background-color: #f7faf5;
                border: 2px dashed #8caf83;
                border-radius: 12px;
}}

            input{{
                display: block;
                margin: 15px 0;
}}

            button{{
                padding: 12px 20px;
                border: none;
                border-radius: 8px;
                background-color: #3d6b35;
                color: white;
                font-size: 16px;
                cursor: pointer;
}}

            .resultado{{
                margin-top: 25px;
                padding: 20px;
                min-height: 80px;
                background-color: #fffbea;
                border-left: 5px solid #e1b83b;
                border-radius: 8px;
                white-space: pre-wrap;
                line-height: 1.7;
}}

            .dica{{
                margin-top: 20px;
                color: #52634e;
                font-size: 14px;
                line-height: 1.5;
}}
        </style>
    </head>

    <body>

        <main class="painel">

            <h1>🥕 Feira Fácil</h1>

            <p class="descricao">
                Envie uma imagem contendo o nome de um produto,
                sua quantidade, unidade e preço.
            </p>

            <form
                action="/ler"
                method="POST"
                enctype="multipart/form-data"
            >

                <label for="imagem">
                    <strong>📷 Escolha ou fotografe uma imagem:</strong>
                </label>

                <input
                    type="file"
                    id="imagem"
                    name="imagem"
                    accept="image/*"
                    capture="environment"
                    required
                >

                <button type="submit">
                    👁️ Executar OCR
                </button>

            </form>

            <section class="resultado">

                <strong>Texto reconhecido:</strong>

                <br><br>

{resultado}

            </section>

            <p class="dica">
                💡 Para o primeiro teste, use uma imagem clara,
                reta, com fundo branco e texto preto.
            </p>

        </main>

    </body>

    </html>
    """


@app.route("/")
def pagina_inicial():
    return render_template("index.html")


@app.route("/ler", methods=["POST"])
def executar_ocr():

    if "imagem" not in request.files:
        return criar_pagina("Nenhuma imagem foi enviada.")

    imagem = request.files["imagem"]

    if imagem.filename == "":
        return criar_pagina("Nenhuma imagem foi selecionada.")

    nome_seguro = secure_filename(imagem.filename)

    caminho = os.path.join(PASTA_UPLOADS, nome_seguro)

    imagem.save(caminho)

    textos_encontrados = leitor.readtext(caminho, detail=0, paragraph=True)

    texto_completo = "\n".join(textos_encontrados)

    if not texto_completo:
        texto_completo = "Nenhum texto foi reconhecido na imagem."

    print("\n" + "=" * 45)
    print("🥕 TEXTO RECONHECIDO PELO OCR")
    print("=" * 45)
    print(texto_completo)
    print("=" * 45)

    return criar_pagina(texto_completo)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
