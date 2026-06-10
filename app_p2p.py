import asyncio
import websockets
import json
import aioconsole
import os
from datetime import datetime
import banco  # Seu banco de dados original
from descoberta import iniciar_radar  # O script UDP que criamos

# ==========================================
# ESTADO GLOBAL E MEMÓRIA
# ==========================================
contatos_online = {} # Alimentado magicamente pelo radar UDP
mensagens_nao_lidas = []
historico_conversas = {}
estado_cli = 'MENU'
contato_ativo = None

meu_telefone = ""
meu_nome = ""
minha_porta_ws = 0

def limpar_tela():
    os.system('cls' if os.name == 'nt' else 'clear')

def carregar_tela_chat(telefone_alvo):
    # Usa o nome do radar UDP se o cara estiver online, senão usa o número
    nome_alvo = contatos_online.get(telefone_alvo, {}).get('nome', telefone_alvo)
    print(f"=== CONVERSA COM: {nome_alvo} ===")
    print("Digite /voltar para sair.")
    print("="*50)
    
    if telefone_alvo in historico_conversas:
        for msg in historico_conversas[telefone_alvo]:
            prefixo = "Você" if msg['de'] == meu_telefone else msg.get('nome', msg['de'])
            print(f"[{msg['hora']}] {prefixo}: {msg['texto']}")
    print(" ")

# ==========================================
# LADO SERVIDOR (RECEBENDO E ESCUTANDO)
# ==========================================
async def servidor_local(websocket):
    """Fica escutando mensagens chegando de outros peers."""
    global mensagens_nao_lidas, historico_conversas
    try:
        async for mensagem in websocket:
            dados = json.loads(mensagem)
            tipo = dados.get('tipo')

            if tipo == 'nova_mensagem':
                remetente = dados['remetente']
                nome_remetente = dados.get('nome_remetente', remetente) 
                texto = dados['texto']
                id_msg = dados['id_mensagem']
                hora = dados.get('timestamp', datetime.now().strftime("%d/%m/%Y %H:%M"))
                
                # Salva no histórico da sessão
                if remetente not in historico_conversas:
                    historico_conversas[remetente] = []
                historico_conversas[remetente].append({"de": remetente, "nome": nome_remetente, "texto": texto, "hora": hora}) 
                
                # Opcional: Salvar a mensagem recebida no seu banco de dados aqui
                
                # Manda confirmação de entrega de volta para quem enviou
                await websocket.send(json.dumps({
                    "tipo": "confirmacao_entrega",
                    "id_mensagem": id_msg,
                    "remetente": remetente,
                    "contato": meu_telefone
                }))

                if estado_cli == 'CHAT' and remetente == contato_ativo:
                    print(f"\n[{hora}] {nome_remetente}: {texto}")
                    # Manda confirmação de leitura instantânea
                    await websocket.send(json.dumps({
                        "tipo": "confirmacao_leitura",
                        "id_mensagem": id_msg,
                        "remetente": remetente,
                        "contato": meu_telefone
                    }))
                else:
                    print(f"\n❗ Nova mensagem de {nome_remetente} ({remetente})") 
                    mensagens_nao_lidas.append({"id_mensagem": id_msg, "remetente": remetente})

            elif tipo in ['confirmacao_entrega', 'confirmacao_leitura']:
                status_db = 'entregue' if tipo == 'confirmacao_entrega' else 'lida'
                banco.atualizar_status_mensagem(dados['id_mensagem'], status_db)
                
                simbolo = "✔" if status_db == 'entregue' else "✔✔"
                if estado_cli == 'CHAT' and dados['contato'] == contato_ativo:
                    print(f" {simbolo}")

    except websockets.exceptions.ConnectionClosed:
        pass

async def iniciar_servidor_ws():
    """Roda o servidor WebSocket local em background."""
    async with websockets.serve(servidor_local, "0.0.0.0", minha_porta_ws):
        await asyncio.Future()

# ==========================================
# LADO CLIENTE (ENVIANDO MENSAGENS)
# ==========================================
async def enviar_mensagem_p2p(destinatario, texto):
    """Envia uma mensagem abrindo uma conexão relâmpago com o destino."""
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # 1. Salva no banco de dados local (Status padrão: 'enviada')
    id_msg, _ = banco.salvar_mensagem(meu_telefone, destinatario, texto)
    
    # 2. Atualiza a tela localmente
    if destinatario not in historico_conversas:
        historico_conversas[destinatario] = []
    historico_conversas[destinatario].append({"de": meu_telefone, "texto": texto, "hora": agora})

    # 3. Roteamento P2P: Ele está online na rede local?
    if destinatario in contatos_online:
        ip_destino = contatos_online[destinatario]['ip']
        porta_destino = contatos_online[destinatario]['porta_ws']
        uri = f"ws://{ip_destino}:{porta_destino}"
        
        pacote = {
            "tipo": "nova_mensagem",
            "id_mensagem": id_msg,
            "remetente": meu_telefone,
            "nome_remetente": meu_nome,
            "texto": texto,
            "timestamp": agora
        }
        
        try:
            # Conecta, envia e espera rapidinho a confirmação de entrega do outro lado
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps(pacote))
                # Espera a resposta do peer (status entregue)
                resposta = await ws.recv()
                dados_resp = json.loads(resposta)
                if dados_resp.get('tipo') == 'confirmacao_entrega':
                    banco.atualizar_status_mensagem(id_msg, 'entregue')
                    return "✔"
        except Exception:
            return " " # Erro na conexão, fica apenas como 'enviada' no banco
    else:
        # Usuário não está no radar UDP, a mensagem fica aguardando no banco
        return " "

# ==========================================
# INTERFACE CLI ASSÍNCRONA
# ==========================================
async def gerenciar_interface():
    global estado_cli, contato_ativo
    
    while True:
        if estado_cli == 'MENU':
            print("\n" + "="*40)
            print(f" NÓ: {meu_nome} | PORTA: {minha_porta_ws}")
            print("="*40)
            print("1. Ver Radares (Usuários Online na Rede)")
            print("2. Abrir Chat com Número")
            print("3. Desconectar-se")
            print("="*40)
            
            opcao = await aioconsole.ainput("Selecione: ")

            if opcao == '1':
                limpar_tela()
                if not contatos_online:
                    print("\nNenhum usuário detectado na rede local no momento.")
                else:
                    print("\n--- RADAR P2P (LAN) ---")
                    for tel, info in contatos_online.items():
                        print(f" 🟢 {info['nome']} ({tel}) -> {info['ip']}:{info['porta_ws']}")
                await aioconsole.ainput("\nPressione Enter para voltar...")
                limpar_tela()

            elif opcao == '2':
                num = await aioconsole.ainput("Número do destinatário: ")
                if num.strip():
                    contato_ativo = num
                    estado_cli = 'CHAT'
                    # Limpa notificações não lidas
                    mensagens_nao_lidas[:] = [m for m in mensagens_nao_lidas if m['remetente'] != contato_ativo]
                    limpar_tela() 
                    carregar_tela_chat(contato_ativo)

            elif opcao == '3':
                print("Encerrando...")
                os._exit(0)

        elif estado_cli == 'CHAT':
            msg = await aioconsole.ainput(f"")
            if msg == '/voltar':
                estado_cli = 'MENU'
                contato_ativo = None
                limpar_tela() 
            elif msg.strip():
                # Dispara a mensagem e aguarda para printar o checkmark (✔)
                status_icon = await enviar_mensagem_p2p(contato_ativo, msg)
                # Como a tela subiu uma linha ao digitar, imprimimos o status na mesma linha
                print(f"\033[F\033[KVocê: {msg} {status_icon}") 

# ==========================================
# BOOTSTRAP DA APLICAÇÃO
# ==========================================
async def main():
    global meu_telefone, meu_nome, minha_porta_ws
    banco.inicializar_banco()
    
    print(f"===== INICIALIZAÇÃO P2P =====")
    meu_telefone = input("Seu Telefone (ID): ")
    meu_nome = input("Seu Nome/Apelido: ")
    while True:
        porta_input = input("Porta local para operar (ex: 8001, 8002): ")
        try:
            minha_porta_ws = int(porta_input)
            break  # Se a conversão para inteiro deu certo, quebra o loop e continua
        except ValueError:
            print("[!] Por favor, digite um número válido para a porta (ex: 8001).")    
            limpar_tela()
    
    print("Iniciando nó P2P na rede local...")

    # 1. Inicia o radar UDP (Descobrir e ser descoberto)
    await iniciar_radar(meu_telefone, meu_nome, minha_porta_ws, contatos_online)
    
    # 2. Inicia o servidor local e a Interface em paralelo
    await asyncio.gather(
        iniciar_servidor_ws(),
        gerenciar_interface()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAplicação encerrada.")