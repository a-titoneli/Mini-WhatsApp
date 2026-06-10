import asyncio
import json
import socket
import time

PORTA_BROADCAST = 5000
TIMEOUT_OFFLINE = 10 

class DescobertaP2P(asyncio.DatagramProtocol):
    def __init__(self, meu_telefone, meu_nome, minha_porta_ws, contatos_online):
        self.meu_telefone = meu_telefone
        self.meu_nome = meu_nome
        self.minha_porta_ws = minha_porta_ws
        # Este dicionário substituirá o 'usuarios_conectados' do seu antigo servidor
        self.contatos_online = contatos_online 

    def connection_made(self, transport):
        self.transport = transport
        sock = self.transport.get_extra_info('socket')
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def datagram_received(self, data, addr):
        try:
            pacote = json.loads(data.decode('utf-8'))
            telefone = pacote.get("telefone")
            
            # Se não sou eu mesmo, adiciono/atualizo na lista de online
            if telefone and telefone != self.meu_telefone:
                self.contatos_online[telefone] = {
                    "nome": pacote.get("nome"),
                    "ip": addr[0],
                    "porta_ws": pacote.get("porta_ws"),
                    "last_seen": time.time()
                }
        except Exception:
            pass

async def enviar_heartbeat_udp(transport, meu_telefone, meu_nome, minha_porta_ws):
    """Grita para a rede local: 'Eu existo, este é meu IP e Porta!'"""
    pacote = json.dumps({
        "telefone": meu_telefone, 
        "nome": meu_nome, 
        "porta_ws": minha_porta_ws
    }).encode('utf-8')
    
    while True:
        transport.sendto(pacote, ('<broadcast>', PORTA_BROADCAST))
        await asyncio.sleep(3)

async def limpar_usuarios_offline(contatos_online):
    """Remove da memória quem parou de mandar sinal (caiu/fechou app)."""
    while True:
        agora = time.time()
        para_remover = [tel for tel, dados in contatos_online.items() 
                        if agora - dados["last_seen"] > TIMEOUT_OFFLINE]
        
        for tel in para_remover:
            del contatos_online[tel]
            # Aqui podemos colocar um aviso opcional: print(f"Usuário {tel} ficou offline")
            
        await asyncio.sleep(2)

async def iniciar_radar(meu_telefone, meu_nome, minha_porta_ws, contatos_online):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DescobertaP2P(meu_telefone, meu_nome, minha_porta_ws, contatos_online),
        local_addr=('0.0.0.0', PORTA_BROADCAST),
        allow_broadcast=True
    )
    asyncio.create_task(enviar_heartbeat_udp(transport, meu_telefone, meu_nome, minha_porta_ws))
    asyncio.create_task(limpar_usuarios_offline(contatos_online))