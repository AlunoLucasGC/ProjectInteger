-- Esquema SQLite do Feira Fácil. O banco inteiro é armazenado em feira_facil.db.
CREATE TABLE IF NOT EXISTS tb_categorias (
    id_categoria INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS tb_produtores (
    id_produtor INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    telefone TEXT,
    email TEXT UNIQUE,
    senha TEXT,
    cidade TEXT,
    data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tb_produtos (
    id_produto INTEGER PRIMARY KEY,
    id_produtor INTEGER NOT NULL,
    id_categoria INTEGER NOT NULL,
    nome TEXT NOT NULL,
    descricao TEXT,
    quantidade NUMERIC,
    unidade TEXT,
    preco NUMERIC,
    foto_produto TEXT,
    foto_ficha TEXT,
    disponivel INTEGER NOT NULL DEFAULT 1 CHECK (disponivel IN (0, 1)),
    data_cadastro TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_categoria) REFERENCES tb_categorias (id_categoria),
    FOREIGN KEY (id_produtor) REFERENCES tb_produtores (id_produtor)
);

CREATE INDEX IF NOT EXISTS idx_produtos_produtor ON tb_produtos (id_produtor);
CREATE INDEX IF NOT EXISTS idx_produtos_categoria ON tb_produtos (id_categoria);
