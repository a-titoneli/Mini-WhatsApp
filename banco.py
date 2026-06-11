import sqlite3

def inicializar_banco():
    # Cria o arquivo do banco de dados na mesma pasta (se não existir)
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            telefone TEXT PRIMARY KEY,
            nome TEXT,
            apelido TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            remetente TEXT,
            destinatario TEXT,
            texto TEXT,
            status TEXT DEFAULT 'enviada',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conexao.commit()
    conexao.close()
    print("Banco de dados inicializado")

def salvar_usuario(telefone, nome):
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    cursor.execute(
        "REPLACE INTO usuarios (telefone, nome, apelido) VALUES (?, ?, ?)",
        (telefone, nome, nome) 
    )
    conexao.commit()
    conexao.close()

def buscar_nome_usuario(telefone):
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    cursor.execute("SELECT nome FROM usuarios WHERE telefone = ?", (telefone,))
    resultado = cursor.fetchone()
    conexao.close()
    return resultado[0] if resultado else telefone

def salvar_mensagem(remetente, destinatario, texto):
    import datetime
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    agora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    cursor.execute(
        "INSERT INTO mensagens (remetente, destinatario, texto, status, timestamp) VALUES (?, ?, ?, 'enviada', ?)",
        (remetente, destinatario, texto, agora)
    )
    id_mensagem = cursor.lastrowid 
    conexao.commit()
    conexao.close()
    return id_mensagem, agora

def buscar_mensagens_pendentes(telefone):
    conexao = sqlite3.connect('banco_de_dados.db')
    conexao.row_factory = sqlite3.Row 
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT id, remetente, texto, status, timestamp FROM mensagens WHERE destinatario = ? AND status != 'lida'",
        (telefone,)
    )
    pendentes = [dict(row) for row in cursor.fetchall()]
    conexao.close()
    return pendentes

def atualizar_status_mensagem(id_mensagem, novo_status):
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    cursor.execute("UPDATE mensagens SET status = ? WHERE id = ?", (novo_status, id_mensagem))
    conexao.commit()
    conexao.close()

if __name__ == "__main__":
    inicializar_banco()