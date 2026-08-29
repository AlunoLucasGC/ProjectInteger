# 🌱 Feira Fácil

> MVP de um catálogo de produtos rurais que transforma fichas preenchidas em anúncios publicados após revisão do produtor.

[![Python](https://img.shields.io/badge/Python-3.x-blue?logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-black?logo=flask)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-database-003B57?logo=sqlite)](https://www.sqlite.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-image%20processing-5C3EE8?logo=opencv)](https://opencv.org/)

## 📖 Sobre o projeto

O **Feira Fácil** foi desenvolvido como projeto integrador do curso de Desenvolvimento de Sistemas. A proposta é aproximar produtores rurais e consumidores por meio de um catálogo simples de produtos locais.

O diferencial do MVP é o fluxo de cadastro: o produtor envia uma foto de uma ficha padronizada, o sistema realiza OCR para sugerir os dados, o produtor revisa as informações e somente então o anúncio é publicado no catálogo.

**Importante:** o projeto não utiliza IA generativa. O reconhecimento de texto é realizado localmente com **EasyOCR**, enquanto o **OpenCV** faz o pré-processamento da imagem.

## ✨ Funcionalidades

- 📷 Upload de fichas em JPG, JPEG, PNG e WEBP.
- 🔎 Leitura da ficha com OCR em português.
- 🧹 Pré-processamento da imagem para melhorar a leitura.
- ✏️ Revisão e correção dos dados antes da publicação.
- ✅ Validação de produto, quantidade, unidade, preço e dados do produtor.
- 🛒 Catálogo público de produtos disponíveis.
- 🔍 Busca por produto ou produtor.
- 📞 Contato direto com o produtor.
- 🗑️ Exclusão de anúncios.
- 💾 Persistência em banco SQLite.
- 🔐 Validação de extensão, nome seguro do arquivo e limite de upload de 8 MB.
- 🧹 Remoção dos arquivos temporários utilizados pelo OCR após o processamento.

## 🧠 Fluxo da aplicação

```text
┌─────────────────┐
│ Produtor envia  │
│ foto da ficha   │
└────────┬────────┘
         ↓
┌─────────────────┐
│   OpenCV        │
│ Pré-processa    │
│     imagem      │
└────────┬────────┘
         ↓
┌─────────────────┐
│    EasyOCR      │
│ Extrai o texto  │
└────────┬────────┘
         ↓
┌─────────────────┐
│ Organiza dados  │
│ produto/preço/  │
│ quantidade/etc. │
└────────┬────────┘
         ↓
┌─────────────────┐
│     Revisão     │
│ pelo produtor   │
└────────┬────────┘
         ↓
┌─────────────────┐
│    Validação    │
└────────┬────────┘
         ↓
┌─────────────────┐
│     SQLite      │
│ Salva anúncio   │
└────────┬────────┘
         ↓
┌─────────────────┐
│    Catálogo     │
│    público      │
└─────────────────┘
```

## 🏗️ Arquitetura

```text
Navegador
    ↓
Flask
    ├── Templates HTML
    ├── Validação
    ├── OCR
    │    ├── OpenCV
    │    └── EasyOCR
    ↓
SQLite
```

### Principais componentes

- **Flask:** servidor web e gerenciamento das rotas.
- **Jinja2:** renderização das páginas HTML.
- **OpenCV:** tratamento e preparação das imagens antes do OCR.
- **EasyOCR:** reconhecimento de texto em português.
- **SQLite:** armazenamento local de produtores, categorias e produtos.
- **HTML/CSS:** interface do catálogo e das telas de cadastro/revisão.

## 🛠️ Tecnologias

| Tecnologia | Utilização |
|---|---|
| Python | Linguagem principal |
| Flask | Aplicação web |
| EasyOCR | Reconhecimento de texto |
| OpenCV | Processamento de imagens |
| SQLite | Banco de dados |
| HTML5 | Estrutura das páginas |
| CSS3 | Interface |
| Git/GitHub | Versionamento |

As dependências Python estão definidas em [`requirements.txt`](requirements.txt). citeturn8file0

## 📂 Estrutura do projeto

```text
ProjectInteger/
│
├── app.py
├── database.sql
├── requirements.txt
├── ver_banco.py
├── .gitignore
│
├── static/
│   └── estilo.css
│
├── templates/
│   ├── index.html
│   ├── cadastro.html
│   ├── resultado.html
│   ├── produto.html
│   └── vendedor.html
│
└── uploads/
```

O projeto atualmente separa templates, estilos, lógica da aplicação e esquema do banco em arquivos e diretórios próprios. citeturn6file0turn9file0turn10file0

## 🗄️ Banco de dados

O projeto utiliza **SQLite** e cria o banco automaticamente ao iniciar a aplicação. O esquema possui entidades para:

- Produtores
- Categorias
- Produtos

Também existem chaves estrangeiras e índices para relacionamento entre produtos, produtores e categorias. citeturn13file0

O arquivo `feira_facil.db` é gerado localmente e não deve ser versionado no Git, conforme o `.gitignore`. citeturn12file0

## 📋 Formato da ficha

Para obter melhores resultados no OCR, a ficha deve utilizar uma linha por campo:

```text
PRODUTO: Tomate
QUANTIDADE: 2 KG
PREÇO: R$ 8,50
```

O sistema extrai os campos principais e apresenta os valores em uma tela de revisão antes de gravá-los no banco. citeturn18file0

## ⚙️ Como executar

### 1. Clone o repositório

```bash
git clone https://github.com/AlunoLucasGC/ProjectInteger.git
cd ProjectInteger
```

### 2. Crie um ambiente virtual

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instale as dependências

```bash
python -m pip install -r requirements.txt
```

### 4. Execute a aplicação

```bash
python app.py
```

### 5. Acesse no navegador

```text
http://127.0.0.1:5000
```

Na primeira utilização do OCR, o EasyOCR pode levar mais tempo para carregar o modelo. O leitor é reutilizado nas próximas leituras para evitar recarregamentos desnecessários. citeturn11file0

## 🔎 Consultando o banco

Depois de executar a aplicação e criar registros, é possível consultar o SQLite pelo script auxiliar:

```bash
python ver_banco.py
```

Também é possível consultar categorias, produtores e tabelas:

```bash
python ver_banco.py produtores
python ver_banco.py categorias
python ver_banco.py tabelas
```

O script foi criado para facilitar a inspeção do banco sem depender do comando `sqlite3` instalado no sistema. citeturn14file0

## 🔒 Boas práticas implementadas

- Limite de 8 MB para uploads.
- Restrição dos formatos de imagem aceitos.
- Uso de `secure_filename` para os arquivos enviados.
- Nome único para arquivos temporários.
- Exclusão dos arquivos temporários após o OCR.
- Validação dos dados antes da persistência.
- Chaves estrangeiras ativadas nas conexões SQLite.
- `SECRET_KEY` configurável por variável de ambiente para ambientes de produção. citeturn11file0turn13file0

## 🚧 Status

**MVP funcional / em evolução**

O projeto já possui o fluxo principal de cadastro por ficha, OCR, revisão, validação, persistência e catálogo. Algumas telas e funcionalidades adicionais ainda podem ser evoluídas conforme o projeto avance.

## 🔮 Próximas evoluções

- [ ] Autenticação de produtores.
- [ ] Área individual do produtor.
- [ ] Edição de anúncios.
- [ ] Categorias selecionáveis no cadastro.
- [ ] Geolocalização e filtros por região.
- [ ] Fotos próprias dos produtos.
- [ ] Integração com WhatsApp.
- [ ] Testes automatizados.
- [ ] Deploy da aplicação.
- [ ] Migração para PostgreSQL caso a escala do projeto exija.

## 👨‍💻 Autor

**Lucas Goerler Colvero**

Projeto desenvolvido como parte da formação em Desenvolvimento de Sistemas e para construção de portfólio profissional.

---

⭐ Se você gostou do projeto, considere deixar uma estrela no repositório.
