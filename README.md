# 🌱 Feira Fácil

O **Feira Fácil** é um MVP para aproximar produtores rurais e consumidores. O produtor envia uma foto de uma ficha padronizada; o sistema usa OCR para sugerir os dados do anúncio; e o produtor revisa tudo antes da publicação.

> Este projeto não usa IA generativa. O reconhecimento é feito por OCR local com EasyOCR e pré-processamento de imagem com OpenCV.

## Funcionalidades

- Envio seguro de ficha em JPG, PNG ou WEBP (até 8 MB).
- Pré-processamento da imagem e OCR em português.
- Extração de produto, quantidade, unidade e preço.
- Tela de revisão editável: o OCR nunca publica dados sem confirmação.
- Validação dos dados e armazenamento local em SQLite.
- Foto genérica real do produto: ao publicar, o sistema consulta a API do Unsplash e guarda localmente uma versão reduzida da imagem encontrada.
- Catálogo público com busca por produto ou produtor e botão de contato direto.

## Arquitetura

```text
Navegador → Flask → OpenCV + EasyOCR → revisão → Unsplash → SQLite → catálogo
```

- **Interface Flask:** páginas de catálogo, envio e revisão.
- **OCR:** a imagem é ampliada, convertida para tons de cinza e binarizada antes da leitura.
- **Fotos do catálogo:** depois da revisão, uma busca pelo nome do produto é enviada à API do Unsplash. Crie uma chave em [Unsplash Developers](https://unsplash.com/developers) e defina `UNSPLASH_ACCESS_KEY` antes de iniciar o app. O app baixa no máximo 2 MB e salva a miniatura em `uploads/catalogo/`; novos anúncios com o mesmo produto reutilizam a foto. Se a chave não estiver configurada, a API estiver indisponível ou não houver resultado, o anúncio ainda é publicado com o marcador padrão.
- **Persistência:** um único arquivo SQLite (`feira_facil.db`) armazena produtores,
  categorias e produtos, com chaves estrangeiras ativadas em cada conexão.
- **Segurança básica:** extensão permitida, nome de arquivo seguro/único e limite de tamanho do upload.

## Como executar

1. Crie e ative um ambiente virtual.
2. Instale as dependências:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Para ativar as fotos genéricas, configure a chave de acesso do Unsplash:

   ```bash
   export UNSPLASH_ACCESS_KEY="sua_chave_do_unsplash"
   ```

4. Inicie a aplicação:

   ```bash
   python app.py
   ```

5. Acesse `http://127.0.0.1:5000`.

### Banco de dados

O esquema SQLite está versionado em [`database.sql`](database.sql) e é criado
automaticamente ao iniciar a aplicação. Não é necessário instalar ou configurar
um servidor MySQL: basta manter o arquivo `feira_facil.db` junto da aplicação.

Ao atualizar uma instalação que usava a tabela local antiga `produtos`, a
aplicação importa seus anúncios uma única vez para `tb_produtores`,
`tb_categorias` e `tb_produtos`. Os novos anúncios sem categoria explícita ficam
em **Sem categoria**, preservando o fluxo atual da interface.

### Consultar o banco no Windows

O arquivo `feira_facil.db` é binário, portanto é normal que o VS Code não consiga
exibi-lo como texto. Também não é obrigatório instalar o comando `sqlite3`.
Depois de iniciar a aplicação e publicar um anúncio, use o script incluído:

```bash
python ver_banco.py
```

Ele mostra os produtos, seus produtores e categorias. Para outras consultas,
use `python ver_banco.py produtores`, `python ver_banco.py categorias` ou
`python ver_banco.py tabelas`.

Para produção, defina uma `SECRET_KEY` forte no ambiente e execute atrás de um servidor WSGI. Não use o modo de depuração em produção.

O esquema SQLite está versionado em [`database.sql`](database.sql) e é criado
automaticamente ao iniciar a aplicação. Não é necessário instalar ou configurar
um servidor MySQL: basta manter o arquivo `feira_facil.db` junto da aplicação.

Ao atualizar uma instalação que usava a tabela local antiga `produtos`, a
aplicação importa seus anúncios uma única vez para `tb_produtores`,
`tb_categorias` e `tb_produtos`. Os novos anúncios sem categoria explícita ficam
em **Sem categoria**, preservando o fluxo atual da interface.

### Consultar o banco no Windows

O arquivo `feira_facil.db` é binário, portanto é normal que o VS Code não consiga
exibi-lo como texto. Também não é obrigatório instalar o comando `sqlite3`.
Depois de iniciar a aplicação e publicar um anúncio, use o script incluído:

```bash
python ver_banco.py
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
