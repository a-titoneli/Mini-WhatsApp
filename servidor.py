import asyncio
import websockets
import json
import sqlite3
from datetime import datetime

usuarios_conectados = {}


# FUNÇÕES DE BANCO DE DADOS

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
    """Busca o nome do usuário no banco. Se não achar, devolve o próprio número."""
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    cursor.execute("SELECT nome FROM usuarios WHERE telefone = ?", (telefone,))
    resultado = cursor.fetchone()
    conexao.close()
    return resultado[0] if resultado else telefone

def salvar_mensagem(remetente, destinatario, texto):
    conexao = sqlite3.connect('banco_de_dados.db')
    cursor = conexao.cursor()
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
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

# LÓGICA DE REDE E WEBSOCKETS
async def manipulador_de_conexoes(websocket):
    telefone_atual = None
    try:
        async for mensagem_texto in websocket:
            dados = json.loads(mensagem_texto)
            tipo_evento = dados.get('tipo')
            
            if tipo_evento == 'cadastro':
                telefone_atual = dados['telefone']
                nome_atual = dados.get('nome', 'Desconhecido') 
                
                usuarios_conectados[telefone_atual] = websocket
                salvar_usuario(telefone_atual, nome_atual)
                print(f"Usuário conectado: {nome_atual} ({telefone_atual})")
                
                mensagens_offline = buscar_mensagens_pendentes(telefone_atual)
                for msg in mensagens_offline:
                    nome_remetente = buscar_nome_usuario(msg['remetente'])
                    pacote = {
                        "tipo": "nova_mensagem",
                        "id_mensagem": msg['id'],
                        "remetente": msg['remetente'],
                        "nome_remetente": nome_remetente, 
                        "texto": msg['texto'],
                        "timestamp": msg.get('timestamp', 'Hora desconhecida')
                    }
                    await websocket.send(json.dumps(pacote))
                    
            elif tipo_evento == 'enviar_mensagem':
                remetente = telefone_atual
                destinatario = dados['destinatario']
                texto = dados['texto']
                
                id_msg, hora_envio = salvar_mensagem(remetente, destinatario, texto)
                nome_remetente = buscar_nome_usuario(remetente)
                print(f"Mensagem {id_msg} registrada de {nome_remetente} para {destinatario}")
                
                if destinatario in usuarios_conectados:
                    socket_destino = usuarios_conectados[destinatario]
                    pacote_entrega = {
                        "tipo": "nova_mensagem",
                        "id_mensagem": id_msg,
                        "remetente": remetente,
                        "nome_remetente": nome_remetente,
                        "texto": texto,
                        "timestamp": hora_envio
                    }
                    await socket_destino.send(json.dumps(pacote_entrega))

            elif tipo_evento == 'confirmacao_entrega':
                id_msg = dados['id_mensagem']
                remetente_original = dados['remetente']
                atualizar_status_mensagem(id_msg, 'entregue')
                if remetente_original in usuarios_conectados:
                    await usuarios_conectados[remetente_original].send(json.dumps({
                        "tipo": "status_atualizado",
                        "id_mensagem": id_msg,
                        "status": "entregue",
                        "contato": telefone_atual
                    }))

            elif tipo_evento == 'confirmacao_leitura':
                id_msg = dados['id_mensagem']
                remetente_original = dados['remetente']
                atualizar_status_mensagem(id_msg, 'lida')
                if remetente_original in usuarios_conectados:
                    await usuarios_conectados[remetente_original].send(json.dumps({
                        "tipo": "status_atualizado",
                        "id_mensagem": id_msg,
                        "status": "lida",
                        "contato": telefone_atual
                    }))

    except websockets.exceptions.ConnectionClosed:
        pass 
    finally:
        if telefone_atual and telefone_atual in usuarios_conectados:
            del usuarios_conectados[telefone_atual]
            print(f"Usuário desconectado: {telefone_atual}")

async def main():
    async with websockets.serve(manipulador_de_conexoes, "localhost", 8765):
        print("=== Servidor INICIADO ===")
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())