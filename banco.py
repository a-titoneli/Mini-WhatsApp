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

if __name__ == "__main__":
    inicializar_banco()