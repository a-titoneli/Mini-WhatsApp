import socket
import threading
import time
import json

class PeerDiscovery:
    def __init__(self, telefone, nome, porta_ws):
        self.peer_id = telefone
        self.nome = nome
        self.porta_ws = porta_ws
        
        # Porta fixa para a descoberta UDP na rede local
        self.discovery_port = 50000 
        
        # Dicionário para armazenar os peers descobertos
        self.active_peers = {} 
        
        self.running = False
        self.timeout_limit = 15  # Segundos para considerar um peer "morto"

    def _listen_for_broadcasts(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass

        sock.bind(('', self.discovery_port))
        sock.settimeout(2.0) # Permite checar se o programa ainda está rodando

        while self.running:
            try:
                data, addr = sock.recvfrom(1024)
                message = json.loads(data.decode('utf-8'))
                
                sender_id = message.get('peer_id')
                sender_nome = message.get('nome')
                sender_ws_port = message.get('porta_ws')

                # Ignora a própria mensagem de broadcast
                if sender_id != self.peer_id:
                    self.active_peers[sender_id] = {
                        'nome': sender_nome,
                        'ip': addr[0],
                        'porta_ws': sender_ws_port,
                        'last_seen': time.time()
                    }
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[Erro no Listener] {e}")

        sock.close()

    def _broadcast_presence(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        mensagem = json.dumps({
            'peer_id': self.peer_id,
            'nome': self.nome,
            'porta_ws': self.porta_ws
        }).encode('utf-8')

        while self.running:
            try:
                sock.sendto(mensagem, ('192.168.18.255', self.discovery_port))
            except Exception as e:
                print(f"[Erro no Broadcast] {e}")
            
            time.sleep(5) 
            
        sock.close()

    def _cleanup_dead_peers(self):
        while self.running:
            current_time = time.time()
            for p_id in list(self.active_peers.keys()):
                last_seen = self.active_peers[p_id]['last_seen']
                if current_time - last_seen > self.timeout_limit:
                    del self.active_peers[p_id]
            time.sleep(3)

    def start(self):
        self.running = True
        threading.Thread(target=self._listen_for_broadcasts, daemon=True).start()
        threading.Thread(target=self._broadcast_presence, daemon=True).start()
        threading.Thread(target=self._cleanup_dead_peers, daemon=True).start()

    def stop(self):
        self.running = False

    def get_peers(self):
        return self.active_peers.copy()