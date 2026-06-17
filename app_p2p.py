import asyncio
import websockets
import json
import aioconsole
import os
import base64
from datetime import datetime
import banco
from descoberta import PeerDiscovery

# ==========================================
# ESTADO GLOBAL E MEMÓRIA
# ==========================================
radar_p2p = None
mensagens_nao_lidas = []
historico_conversas = {}
estado_cli = 'MENU'
contato_ativo = None

meu_telefone = ""
meu_nome = ""
minha_porta_ws = 0

# Cria a pasta de downloads se ela não existir
PASTA_DOWNLOADS = "downloads_p2p"
os.makedirs(PASTA_DOWNLOADS, exist_ok=True)

def limpar_tela():
    os.system('cls' if os.name == 'nt' else 'clear')

def carregar_tela_chat(telefone_alvo):
    peers_online = radar_p2p.get_peers() if radar_p2p else {}
    nome_alvo = peers_online.get(telefone_alvo, {}).get('nome', telefone_alvo)
    print(f"=== CONVERSA COM: {nome_alvo} ===")
    print("Comandos: /voltar | /arquivo <caminho_do_arquivo>")
    print("="*50)
    
    if telefone_alvo in historico_conversas:
        for msg in historico_conversas[telefone_alvo]:
            prefixo = "Você" if msg['de'] == meu_telefone else msg.get('nome', msg['de'])
            print(f"[{msg['hora']}] {prefixo}: {msg['texto']}")
    print(" ")

# ==========================================
# LADO SERVIDOR (RECEBIMENTO E ESCUTANDO)
# ==========================================
async def servidor_local(websocket):
    global mensagens_nao_lidas, historico_conversas
    try:
        async for mensagem in websocket:
            dados = json.loads(mensagem)
            tipo = dados.get('tipo')
            remetente = dados.get('remetente')
            nome_remetente = dados.get('nome_remetente', remetente)
            id_msg = dados.get('id_mensagem')
            hora = dados.get('timestamp', datetime.now().strftime("%d/%m/%Y %H:%M"))

            if tipo == 'nova_mensagem' or tipo == 'arquivo':
                if tipo == 'nova_mensagem':
                    conteudo_texto = dados['texto']
                else:
                    # Lógica de recebimento de Arquivo
                    nome_arquivo = dados['nome_arquivo']
                    conteudo_b64 = dados['conteudo_b64']
                    
                    # Decodifica o Base64 e salva o arquivo fisicamente
                    caminho_salvo = os.path.join(PASTA_DOWNLOADS, f"{remetente}_{nome_arquivo}")
                    with open(caminho_salvo, "wb") as f:
                        f.write(base64.b64decode(conteudo_b64))
                    
                    conteudo_texto = f"📁 [Arquivo Recebido] {nome_arquivo} -> Salvo em {PASTA_DOWNLOADS}"

                # Salva no histórico da tela
                if remetente not in historico_conversas:
                    historico_conversas[remetente] = []
                historico_conversas[remetente].append({"de": remetente, "nome": nome_remetente, "texto": conteudo_texto, "hora": hora}) 
                
                # Manda confirmação de entrega
                await websocket.send(json.dumps({
                    "tipo": "confirmacao_entrega",
                    "id_mensagem": id_msg,
                    "remetente": remetente,
                    "contato": meu_telefone
                }))

                if estado_cli == 'CHAT' and remetente == contato_ativo:
                    print(f"\n[{hora}] {nome_remetente}: {conteudo_texto}")
                    await websocket.send(json.dumps({
                        "tipo": "confirmacao_leitura",
                        "id_mensagem": id_msg,
                        "remetente": remetente,
                        "contato": meu_telefone
                    }))
                else:
                    alerta = "Novo arquivo" if tipo == 'arquivo' else "Nova mensagem"
                    print(f"\n❗ {alerta} de {nome_remetente} ({remetente})") 
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
    # max_size=None permite receber arquivos de qualquer tamanho sem desconectar
    async with websockets.serve(servidor_local, "0.0.0.0", minha_porta_ws, max_size=None):
        await asyncio.Future()

# ==========================================
# LADO CLIENTE (ENVIANDO MENSAGENS E ARQUIVOS)
# ==========================================
async def enviar_mensagem_p2p(destinatario, texto):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    id_msg, _ = banco.salvar_mensagem(meu_telefone, destinatario, texto)
    
    if destinatario not in historico_conversas:
        historico_conversas[destinatario] = []
    historico_conversas[destinatario].append({"de": meu_telefone, "texto": texto, "hora": agora})

    peers_online = radar_p2p.get_peers() if radar_p2p else {}
    
    if destinatario in peers_online:
        ip_destino = peers_online[destinatario]['ip']
        porta_destino = peers_online[destinatario]['porta_ws']
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
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps(pacote))
                resposta = await ws.recv()
                if json.loads(resposta).get('tipo') == 'confirmacao_entrega':
                    banco.atualizar_status_mensagem(id_msg, 'entregue')
                    return "✔"
        except Exception:
            return " "
    return " "

async def enviar_arquivo_p2p(destinatario, caminho_arquivo):
    if not os.path.exists(caminho_arquivo):
        return "[Erro] Arquivo não encontrado no disco."

    nome_arquivo = os.path.basename(caminho_arquivo)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    texto_historico = f"📁 [Arquivo Enviado] {nome_arquivo}"

    # Lê os bytes e codifica para string Base64
    with open(caminho_arquivo, "rb") as f:
        conteudo_bytes = f.read()
        conteudo_b64 = base64.b64encode(conteudo_bytes).decode('utf-8')

    id_msg, _ = banco.salvar_mensagem(meu_telefone, destinatario, texto_historico)
    
    if destinatario not in historico_conversas:
        historico_conversas[destinatario] = []
    historico_conversas[destinatario].append({"de": meu_telefone, "texto": texto_historico, "hora": agora})

    peers_online = radar_p2p.get_peers() if radar_p2p else {}
    
    if destinatario in peers_online:
        ip_destino = peers_online[destinatario]['ip']
        porta_destino = peers_online[destinatario]['porta_ws']
        uri = f"ws://{ip_destino}:{porta_destino}"
        
        pacote = {
            "tipo": "arquivo",
            "id_mensagem": id_msg,
            "remetente": meu_telefone,
            "nome_remetente": meu_nome,
            "nome_arquivo": nome_arquivo,
            "conteudo_b64": conteudo_b64,
            "timestamp": agora
        }
        try:
            # max_size=None para permitir o envio do payload gigante do Base64
            async with websockets.connect(uri, max_size=None) as ws:
                await ws.send(json.dumps(pacote))
                resposta = await ws.recv()
                if json.loads(resposta).get('tipo') == 'confirmacao_entrega':
                    banco.atualizar_status_mensagem(id_msg, 'entregue')
                    return "✔"
        except Exception as e:
            return " "
    return " "

# ==========================================
# INTERFACE CLI ASSÍNCRONA
# ==========================================
async def gerenciar_interface():
    global estado_cli, contato_ativo
    
    while True:
        if estado_cli == 'MENU':
            print("\n" + "="*40)
            print(f" NÓ: {meu_nome} | PORTA WS: {minha_porta_ws}")
            print("="*40)
            print("1. Ver Radares (Usuários Online na Rede)")
            print("2. Abrir Chat com Número")
            print("3. Desconectar-se")
            print("="*40)
            
            opcao = await aioconsole.ainput("Selecione: ")

            if opcao == '1':
                limpar_tela()
                peers_online = radar_p2p.get_peers() if radar_p2p else {}
                if not peers_online:
                    print("\nNenhum usuário detectado na rede local no momento.")
                else:
                    print("\n--- RADAR P2P (LAN) ---")
                    for tel, info in peers_online.items():
                        print(f" 🟢 {info['nome']} ({tel}) -> {info['ip']}:{info['porta_ws']}")
                await aioconsole.ainput("\nPressione Enter para voltar...")
                limpar_tela()

            elif opcao == '2':
                num = await aioconsole.ainput("Número do destinatário: ")
                if num.strip():
                    contato_ativo = num
                    estado_cli = 'CHAT'
                    mensagens_nao_lidas[:] = [m for m in mensagens_nao_lidas if m['remetente'] != contato_ativo]
                    limpar_tela() 
                    carregar_tela_chat(contato_ativo)

            elif opcao == '3':
                print("Encerrando...")
                if radar_p2p:
                    radar_p2p.stop()
                os._exit(0)

        elif estado_cli == 'CHAT':
            msg = await aioconsole.ainput(f"")
            if msg == '/voltar':
                estado_cli = 'MENU'
                contato_ativo = None
                limpar_tela() 
            elif msg.startswith('/arquivo '):
                # Extrai o caminho digitado após o comando
                caminho = msg.split(' ', 1)[1].strip()
                # Mostra ao usuário que o envio começou e aguarda
                print(f"\033[F\033[KEnviando arquivo '{os.path.basename(caminho)}'...") 
                status_icon = await enviar_arquivo_p2p(contato_ativo, caminho)
                print(f"\033[F\033[KVocê enviou um arquivo: {caminho} {status_icon}")
            elif msg.strip():
                status_icon = await enviar_mensagem_p2p(contato_ativo, msg)
                print(f"\033[F\033[KVocê: {msg} {status_icon}") 

# ==========================================
# BOOTSTRAP DA APLICAÇÃO
# ==========================================
async def main():
    global meu_telefone, meu_nome, minha_porta_ws, radar_p2p
    banco.inicializar_banco()
    
    print(f"===== INICIALIZAÇÃO P2P =====")
    meu_telefone = input("Seu Telefone (ID): ")
    meu_nome = input("Seu Nome/Apelido: ")
    
    while True:
        try:
            minha_porta_ws = int(input("Porta local para operar (ex: 8001, 8002): "))
            break
        except ValueError:
            print("[!] Por favor, digite um número de porta válido.")
            
    limpar_tela()
    print("Iniciando nó P2P na rede local...")

    radar_p2p = PeerDiscovery(meu_telefone, meu_nome, minha_porta_ws)
    radar_p2p.start()
    
    await asyncio.gather(
        iniciar_servidor_ws(),
        gerenciar_interface()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        if radar_p2p:
            radar_p2p.stop()
        print("\nAplicação encerrada.")