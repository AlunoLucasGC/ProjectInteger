# 🌱 Feira Fácil

O **Feira Fácil** é um MVP para aproximar produtores rurais e consumidores. O produtor envia uma foto de uma ficha padronizada; o sistema usa OCR para sugerir os dados do anúncio; e o produtor revisa tudo antes da publicação.

> Este projeto não usa IA generativa. O reconhecimento é feito por OCR local com EasyOCR e pré-processamento de imagem com OpenCV.

## Funcionalidades

- Envio seguro de ficha em JPG, PNG ou WEBP (até 8 MB).
- Pré-processamento da imagem e OCR em português.
- Extração de produto, quantidade, unidade e preço.
- Tela de revisão editável: o OCR nunca publica dados sem confirmação.
- Validação dos dados e armazenamento local em SQLite.
- Catálogo público com busca por produto ou produtor e botão de contato direto.

## Arquitetura

```text
Navegador → Flask → OpenCV + EasyOCR → revisão → SQLite → catálogo
```

- **Interface Flask:** páginas de catálogo, envio e revisão.
- **OCR:** a imagem é ampliada, convertida para tons de cinza e binarizada antes da leitura.
- **Persistência:** SQLite armazena os anúncios publicados para o MVP.
- **Segurança básica:** extensão permitida, nome de arquivo seguro/único e limite de tamanho do upload.

## Como executar

1. Crie e ative um ambiente virtual.
2. Instale as dependências:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Inicie a aplicação:

   ```bash
   python app.py
   ```

4. Acesse `http://127.0.0.1:5000`.

Para produção, defina uma `SECRET_KEY` forte no ambiente e execute atrás de um servidor WSGI. Não use o modo de depuração em produção.

## Formato recomendado da ficha

Use uma linha por campo para aumentar a precisão do OCR:

```text
PRODUTO: Tomate
QUANTIDADE: 2 KG
PREÇO: R$ 8,50
```

Após a leitura, informe também o nome e o telefone/WhatsApp do produtor na tela de revisão.

## Próximas evoluções

- Autenticação para separar os anúncios por produtor.
- Fotos próprias do produto, estoque e edição/exclusão de anúncios.
- Geolocalização de feiras e filtros por região.
- Integração de WhatsApp e pagamentos via PIX.
- Migração para PostgreSQL quando houver múltiplos usuários simultâneos.
