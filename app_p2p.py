import asyncio
import websockets
import json
import aioconsole
import os
import base64
from datetime import datetime
import banco
from descoberta import PeerDiscovery
from video_p2p import VideoCall  # Importando nosso motor de vídeo

# ==========================================
# IMPORTAÇÃO SEGURA DO TKINTER
# ==========================================
USAR_GUI = True
try:
    import tkinter as tk
    from tkinter import filedialog
except ImportError:
    USAR_GUI = False

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
porta_video_local = 0

# Controles da Chamada de Vídeo
chamada_pendente = {} 
sessao_video = None

PASTA_DOWNLOADS = "downloads_p2p"
os.makedirs(PASTA_DOWNLOADS, exist_ok=True)

def limpar_tela():
    os.system('cls' if os.name == 'nt' else 'clear')

def carregar_tela_chat(telefone_alvo):
    peers_online = radar_p2p.get_peers() if radar_p2p else {}
    nome_alvo = peers_online.get(telefone_alvo, {}).get('nome', telefone_alvo)
    print(f"=== CONVERSA COM: {nome_alvo} ===")
    print("Comandos: /voltar | /arquivo | /video | /atender")
    print("="*50)
    
    if telefone_alvo in historico_conversas:
        for msg in historico_conversas[telefone_alvo]:
            prefixo = "Você" if msg['de'] == meu_telefone else msg.get('nome', msg['de'])
            print(f"[{msg['hora']}] {prefixo}: {msg['texto']}")
    print(" ")

# ==========================================
# SELETOR DE ARQUIVOS
# ==========================================
def _abrir_janela_selecao():
    root = tk.Tk()
    root.withdraw() 
    root.attributes('-topmost', True) 
    caminho = filedialog.askopenfilename(title="Selecione o arquivo")
    root.destroy()
    return caminho

async def selecionar_arquivo_async():
    if USAR_GUI:
        return await asyncio.to_thread(_abrir_janela_selecao)
    else:
        print("\n\033[F\033[K[!] Interface gráfica não detectada.")
        caminho = await aioconsole.ainput("Digite o caminho do arquivo: ")
        return caminho.strip() if caminho.strip() else ""

# ==========================================
# LADO SERVIDOR (ESCUTANDO)
# ==========================================
async def servidor_local(websocket):
    global mensagens_nao_lidas, historico_conversas, chamada_pendente, sessao_video
    try:
        async for mensagem in websocket:
            dados = json.loads(mensagem)
            tipo = dados.get('tipo')
            remetente = dados.get('remetente')
            nome_remetente = dados.get('nome_remetente', remetente)
            
            # --- SINALIZAÇÃO DE VÍDEO ---
            if tipo == 'chamada_video':
                ip_chamador = radar_p2p.get_peers().get(remetente, {}).get('ip', '0.0.0.0')
                porta_video_chamador = dados.get('porta_video')
                
                chamada_pendente = {
                    'remetente': remetente,
                    'ip': ip_chamador,
                    'porta_video': porta_video_chamador
                }
                print(f"\n\033[F\033[K📞 [RING] {nome_remetente} está te ligando por vídeo! Digite /atender para aceitar.")
                
            elif tipo == 'aceitar_video':
                ip_destino = radar_p2p.get_peers().get(remetente, {}).get('ip', '0.0.0.0')
                porta_video_destino = dados.get('porta_video')
                
                print(f"\n\033[F\033[K🎥 {nome_remetente} atendeu! Abrindo câmera...")
                sessao_video = VideoCall('0.0.0.0', porta_video_local, ip_destino, porta_video_destino)
                sessao_video.iniciar()

            # --- MENSAGENS E ARQUIVOS ---
            elif tipo in ['nova_mensagem', 'arquivo']:
                id_msg = dados.get('id_mensagem')
                hora = dados.get('timestamp', datetime.now().strftime("%d/%m/%Y %H:%M"))

                if tipo == 'nova_mensagem':
                    conteudo_texto = dados['texto']
                else:
                    nome_arquivo = dados['nome_arquivo']
                    conteudo_b64 = dados['conteudo_b64']
                    caminho_salvo = os.path.join(PASTA_DOWNLOADS, f"{remetente}_{nome_arquivo}")
                    with open(caminho_salvo, "wb") as f:
                        f.write(base64.b64decode(conteudo_b64))
                    conteudo_texto = f"📁 [Arquivo Recebido] {nome_arquivo}"

                if remetente not in historico_conversas:
                    historico_conversas[remetente] = []
                historico_conversas[remetente].append({"de": remetente, "nome": nome_remetente, "texto": conteudo_texto, "hora": hora}) 
                
                await websocket.send(json.dumps({
                    "tipo": "confirmacao_entrega", "id_mensagem": id_msg,
                    "remetente": remetente, "contato": meu_telefone
                }))

                if estado_cli == 'CHAT' and remetente == contato_ativo:
                    print(f"\n[{hora}] {nome_remetente}: {conteudo_texto}")
                    await websocket.send(json.dumps({
                        "tipo": "confirmacao_leitura", "id_mensagem": id_msg,
                        "remetente": remetente, "contato": meu_telefone
                    }))
                else:
                    print(f"\n❗ Nova mensagem de {nome_remetente}") 
                    mensagens_nao_lidas.append({"id_mensagem": id_msg, "remetente": remetente})

            # --- STATUS DE LEITURA ---
            elif tipo in ['confirmacao_entrega', 'confirmacao_leitura']:
                status_db = 'entregue' if tipo == 'confirmacao_entrega' else 'lida'
                banco.atualizar_status_mensagem(dados['id_mensagem'], status_db)
                if estado_cli == 'CHAT' and dados['contato'] == contato_ativo:
                    print(f" {'✔' if status_db == 'entregue' else '✔✔'}")

    except websockets.exceptions.ConnectionClosed:
        pass

async def iniciar_servidor_ws():
    async with websockets.serve(servidor_local, "0.0.0.0", minha_porta_ws, max_size=None):
        await asyncio.Future()

# ==========================================
# LADO CLIENTE (ENVIANDO)
# ==========================================
async def disparar_pacote_ws(destinatario, pacote):
    """Função genérica para enviar pacotes via WebSocket."""
    peers_online = radar_p2p.get_peers() if radar_p2p else {}
    if destinatario in peers_online:
        uri = f"ws://{peers_online[destinatario]['ip']}:{peers_online[destinatario]['porta_ws']}"
        try:
            async with websockets.connect(uri, max_size=None) as ws:
                await ws.send(json.dumps(pacote))
                return await ws.recv() # Retorna a resposta
        except Exception:
            return None
    return None

async def enviar_sinal_video(destinatario, tipo_sinal):
    pacote = {
        "tipo": tipo_sinal,
        "remetente": meu_telefone,
        "nome_remetente": meu_nome,
        "porta_video": porta_video_local
    }
    await disparar_pacote_ws(destinatario, pacote)

async def enviar_mensagem_p2p(destinatario, texto):
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    id_msg, _ = banco.salvar_mensagem(meu_telefone, destinatario, texto)
    
    if destinatario not in historico_conversas:
        historico_conversas[destinatario] = []
    historico_conversas[destinatario].append({"de": meu_telefone, "texto": texto, "hora": agora})

    pacote = {"tipo": "nova_mensagem", "id_mensagem": id_msg, "remetente": meu_telefone, "nome_remetente": meu_nome, "texto": texto, "timestamp": agora}
    resposta = await disparar_pacote_ws(destinatario, pacote)
    
    if resposta and json.loads(resposta).get('tipo') == 'confirmacao_entrega':
        banco.atualizar_status_mensagem(id_msg, 'entregue')
        return "✔"
    return " "

async def enviar_arquivo_p2p(destinatario, caminho_arquivo):
    if not os.path.exists(caminho_arquivo): return "[Erro] Arquivo não encontrado."
    
    nome_arquivo = os.path.basename(caminho_arquivo)
    agora = datetime.now().strftime("%d/%m/%Y %H:%M")
    texto_historico = f"📁 [Arquivo Enviado] {nome_arquivo}"

    with open(caminho_arquivo, "rb") as f:
        conteudo_b64 = base64.b64encode(f.read()).decode('utf-8')

    id_msg, _ = banco.salvar_mensagem(meu_telefone, destinatario, texto_historico)
    if destinatario not in historico_conversas: historico_conversas[destinatario] = []
    historico_conversas[destinatario].append({"de": meu_telefone, "texto": texto_historico, "hora": agora})

    pacote = {"tipo": "arquivo", "id_mensagem": id_msg, "remetente": meu_telefone, "nome_remetente": meu_nome, "nome_arquivo": nome_arquivo, "conteudo_b64": conteudo_b64, "timestamp": agora}
    resposta = await disparar_pacote_ws(destinatario, pacote)
    
    if resposta and json.loads(resposta).get('tipo') == 'confirmacao_entrega':
        banco.atualizar_status_mensagem(id_msg, 'entregue')
        return "✔"
    return " "

# ==========================================
# INTERFACE CLI
# ==========================================
async def gerenciar_interface():
    global estado_cli, contato_ativo, chamada_pendente, sessao_video
    
    while True:
        if estado_cli == 'MENU':
            print("\n" + "="*40)
            print(f" NÓ: {meu_nome} | PORTA WS: {minha_porta_ws}")
            print("="*40)
            print("1. Ver Radares (Usuários Online)")
            print("2. Abrir Chat com Número")
            print("3. Desconectar-se")
            print("="*40)
            
            opcao = await aioconsole.ainput("Selecione: ")

            if opcao == '1':
                limpar_tela()
                peers_online = radar_p2p.get_peers() if radar_p2p else {}
                if not peers_online:
                    print("\nNenhum usuário detectado na rede.")
                else:
                    print("\n--- RADAR P2P (LAN) ---")
                    for tel, info in peers_online.items():
                        print(f" 🟢 {info['nome']} ({tel}) -> IP: {info['ip']}")
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
                if radar_p2p: radar_p2p.stop()
                if sessao_video: sessao_video.parar()
                os._exit(0)

        elif estado_cli == 'CHAT':
            msg = await aioconsole.ainput(f"")
            if msg == '/voltar':
                estado_cli = 'MENU'
                contato_ativo = None
                limpar_tela() 
                
            elif msg == '/video':
                print("\033[F\033[K📞 Chamando por vídeo...")
                await enviar_sinal_video(contato_ativo, 'chamada_video')
                
            elif msg == '/atender':
                if chamada_pendente:
                    remetente = chamada_pendente['remetente']
                    ip_chamador = chamada_pendente['ip']
                    porta_chamador = chamada_pendente['porta_video']
                    
                    print("\033[F\033[K🎥 Atendendo chamada! Ligando câmera...")
                    await enviar_sinal_video(remetente, 'aceitar_video')
                    
                    sessao_video = VideoCall('0.0.0.0', porta_video_local, ip_chamador, porta_chamador)
                    sessao_video.iniciar()
                    chamada_pendente = {} # Limpa o status
                else:
                    print("\033[F\033[K[!] Não há nenhuma chamada de vídeo tocando.")

            elif msg == '/arquivo':
                print("\033[F\033[KAbrindo seletor...")
                caminho = await selecionar_arquivo_async()
                if caminho: 
                    print(f"\033[F\033[KEnviando '{os.path.basename(caminho)}'...") 
                    status_icon = await enviar_arquivo_p2p(contato_ativo, caminho)
                    print(f"\033[F\033[KVocê enviou um arquivo: {os.path.basename(caminho)} {status_icon}")
                else:
                    print("\033[F\033[K[!] Envio cancelado.")
                    
            elif msg.strip():
                status_icon = await enviar_mensagem_p2p(contato_ativo, msg)
                print(f"\033[F\033[KVocê: {msg} {status_icon}") 

# ==========================================
# BOOTSTRAP
# ==========================================
async def main():
    global meu_telefone, meu_nome, minha_porta_ws, porta_video_local, radar_p2p
    banco.inicializar_banco()
    
    print(f"===== INICIALIZAÇÃO P2P =====")
    meu_telefone = input("Seu Telefone (ID): ")
    meu_nome = input("Seu Nome/Apelido: ")
    
    while True:
        try:
            minha_porta_ws = int(input("Porta local para operar (ex: 8001): "))
            break
        except ValueError:
            pass
            
    # Gera a porta de vídeo automaticamente baseada na porta do WebSocket
    porta_video_local = minha_porta_ws + 10000
            
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
        if radar_p2p: radar_p2p.stop()
        if sessao_video: sessao_video.parar()
        print("\nAplicação encerrada.")