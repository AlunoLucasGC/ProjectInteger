# 🌱 Feira Fácil

O **Feira Fácil** é um MVP desenvolvido para conectar produtores rurais e consumidores de forma simples e acessível.

A proposta do projeto é eliminar a necessidade de formulários complexos. O produtor apenas preenche uma ficha padronizada com seus produtos, tira uma foto pelo aplicativo e o sistema utiliza **OCR (Reconhecimento Óptico de Caracteres)** para extrair automaticamente as informações. Após uma tela de revisão, os produtos são publicados para consulta dos consumidores. :contentReference[oaicite:0]{index=0}

## ✨ Funcionalidades

- 📷 Captura de imagem da ficha do produtor
- 🔍 Leitura automática utilizando OCR
- 📝 Extração e organização dos dados em Python
- ✅ Tela de revisão antes da publicação
- 🛒 Consulta de produtos pelos consumidores
- 📞 Contato direto entre consumidor e produtor

## 🏗️ Arquitetura

O sistema é dividido em camadas:

- Aplicativo (captura e consulta)
- API em Python
- Módulo OCR
- Banco de Dados
- API de resposta

Essa separação facilita manutenção, testes e futuras evoluções. :contentReference[oaicite:1]{index=1}

## 🛠️ Tecnologias

- Python
- Flask ou FastAPI
- EasyOCR ou Tesseract OCR
- SQLite / MySQL / PostgreSQL
- OpenCV
- Pillow

## 🚀 Fluxo do Sistema

1. O produtor preenche uma ficha.
2. O aplicativo fotografa a ficha.
3. A imagem é enviada para a API.
4. O OCR extrai o texto.
5. O Python organiza e valida os dados.
6. O produtor confirma as informações.
7. Os produtos ficam disponíveis para consulta. :contentReference[oaicite:2]{index=2}

## 🎯 Objetivo

Desenvolver uma solução simples e acessível para aproximar produtores rurais dos consumidores, reduzindo o tempo de cadastro de produtos através do uso de OCR, sem utilizar Inteligência Artificial Generativa. :contentReference[oaicite:3]{index=3}

## 📈 Melhorias Futuras

- Geolocalização das feiras
- Favoritos
- Fotos dos produtos
- Controle de estoque
- Painel administrativo
- Notificações
- Integração com WhatsApp
- Pagamentos via PIX
