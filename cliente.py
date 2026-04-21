import asyncio
import websockets
import json
import aioconsole
import os
from datetime import datetime

# Estruturas de Memória e Estado
mensagens_nao_lidas = []    
contatos_conhecidos = {}
historico_conversas = {}    
estado_cli = 'MENU'
contato_ativo = None

# ==========================================
# FUNÇÃO DE LIMPEZA DE TELA
# ==========================================
def limpar_tela():
    """Limpa o terminal no Windows (cls) ou Linux/Mac (clear)."""
    os.system('cls' if os.name == 'nt' else 'clear')

# ==========================================
# MARCAR COMO LIDA
# ==========================================
async def marcar_conversa_como_lida(websocket, numero_contato):
    global mensagens_nao_lidas
    mensagens_para_ler = [m for m in mensagens_nao_lidas if m['remetente'] == numero_contato]
    for msg in mensagens_para_ler:
        await websocket.send(json.dumps({
            "tipo": "confirmacao_leitura",
            "id_mensagem": msg['id_mensagem'],
            "remetente": msg['remetente']
        }))
    mensagens_nao_lidas = [m for m in mensagens_nao_lidas if m['remetente'] != numero_contato]

# ==========================================
# RECEBIMENTO E EXIBIÇÃO
# ==========================================
async def escutar_servidor(websocket):
    global mensagens_nao_lidas, contatos_conhecidos, historico_conversas
    try:
        async for mensagem in websocket:
            dados = json.loads(mensagem)
            tipo = dados.get('tipo')

            if tipo == 'nova_mensagem':
                remetente = dados['remetente']
                nome_remetente = dados.get('nome_remetente', remetente) 
                texto = dados['texto']
                id_msg = dados['id_mensagem']
                hora = dados.get('timestamp', 'Hora desconhecida')
                
                contatos_conhecidos[remetente] = nome_remetente 
                if remetente not in historico_conversas:
                    historico_conversas[remetente] = []
                historico_conversas[remetente].append({"de": remetente, "nome": nome_remetente, "texto": texto, "hora": hora}) 
                
                await websocket.send(json.dumps({
                    "tipo": "confirmacao_entrega",
                    "id_mensagem": id_msg,
                    "remetente": remetente
                }))

                if estado_cli == 'CHAT' and remetente == contato_ativo:
                    print(f"\n[{hora}] {nome_remetente}: {texto}")
                    await websocket.send(json.dumps({
                        "tipo": "confirmacao_leitura",
                        "id_mensagem": id_msg,
                        "remetente": remetente
                    }))
                else:
                    print(f"\n❗ Nova mensagem de {nome_remetente}") 
                    mensagens_nao_lidas.append({"id_mensagem": id_msg, "remetente": remetente})

            elif tipo == 'status_atualizado':
                status = "✔" if dados['status'] == 'entregue' else "✔✔"
                print(f"{status}")

    except websockets.exceptions.ConnectionClosed:
        print("\nConexão encerrada.")

# ==========================================
# INTERFACE DE USUÁRIO
# ==========================================
def carregar_tela_chat(telefone_alvo, meu_telefone):
    nome_alvo = contatos_conhecidos.get(telefone_alvo, telefone_alvo) 
    print(f"=== CONVERSA COM: {nome_alvo} ===")
    print("Digite /voltar para sair.")
    print("="*50)
    
    if telefone_alvo in historico_conversas:
        for msg in historico_conversas[telefone_alvo]:
            if msg['de'] == meu_telefone:
                prefixo = "Você"
            else:
                prefixo = msg.get('nome', msg['de']) 
            print(f"[{msg['hora']}] {prefixo}: {msg['texto']}")
    print(" ")

async def gerenciar_interface(websocket, meu_telefone, meu_nome):
    global estado_cli, contato_ativo
    
    while True:
        if estado_cli == 'MENU':
            print("\n" + "="*40)
            print(f" USUÁRIO: {meu_nome}")
            print("="*40)
            print("1. Conversas")
            print("2. Enviar nova mensagem")
            print("3. Desconectar-se")
            print("="*40)
            
            opcao = await aioconsole.ainput("Selecione: ")

            if opcao == '1':
                if not contatos_conhecidos:
                    print("\nNenhuma conversa.")
                    continue
                
                lista = list(contatos_conhecidos.keys())
                for i, num in enumerate(lista):
                    nome = contatos_conhecidos[num] 
                    tem_pendente = any(m['remetente'] == num for m in mensagens_nao_lidas)
                    aviso = "  🟢" if tem_pendente else ""
                    print(f"[{i}] {nome} ({num}){aviso}") 
                
                escolha = await aioconsole.ainput("\nEscolha a opção ou V para voltar: ")
                if escolha.upper() != 'V':
                    try:
                        contato_ativo = lista[int(escolha)]
                        estado_cli = 'CHAT'
                        await marcar_conversa_como_lida(websocket, contato_ativo)
                        limpar_tela() 
                        carregar_tela_chat(contato_ativo, meu_telefone)
                    except: print("Seleção inválida.")

            elif opcao == '2':
                num = await aioconsole.ainput("Número do destinatário: ")
                if num.strip():
                    contato_ativo = num
                    if num not in contatos_conhecidos: 
                        contatos_conhecidos[num] = num
                    estado_cli = 'CHAT'
                    await marcar_conversa_como_lida(websocket, contato_ativo)
                    limpar_tela() 
                    carregar_tela_chat(contato_ativo, meu_telefone)

            elif opcao == '3':
                break

        elif estado_cli == 'CHAT':
            msg = await aioconsole.ainput(f"")
            if msg == '/voltar':
                estado_cli = 'MENU'
                contato_ativo = None
                limpar_tela() 
            elif msg.strip():
                await websocket.send(json.dumps({
                    "tipo": "enviar_mensagem",
                    "destinatario": contato_ativo,
                    "texto": msg
                }))
                
                agora = datetime.now().strftime("%d/%m/%Y %H:%M")
                if contato_ativo not in historico_conversas:
                    historico_conversas[contato_ativo] = []
                historico_conversas[contato_ativo].append({"de": meu_telefone, "texto": msg, "hora": agora})

async def main():
    print(f"===== LOGIN =====")
    meu_telefone = input("Seu Telefone: ")
    meu_nome = input("Nome ou Apelido? ")
    limpar_tela()
    
    async with websockets.connect("ws://localhost:8765") as ws:
    
        await ws.send(json.dumps({"tipo": "cadastro", "telefone": meu_telefone, "nome": meu_nome})) 
        await asyncio.gather(
            escutar_servidor(ws),
            gerenciar_interface(ws, meu_telefone, meu_nome)
        )

if __name__ == "__main__":
    asyncio.run(main())