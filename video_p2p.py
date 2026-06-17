import cv2
import socket
import threading
import numpy as np

class VideoCall:
    def __init__(self, meu_ip, minha_porta_video, ip_destino, porta_destino):
        self.meu_ip = meu_ip
        self.minha_porta_video = minha_porta_video
        self.ip_destino = ip_destino
        self.porta_destino = porta_destino
        
        self.rodando = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', self.minha_porta_video))

    def _receber_video(self):
        print("[Vídeo] Aguardando conexão de vídeo...")
        while self.rodando:
            try:
                self.sock.settimeout(2.0)
                data, addr = self.sock.recvfrom(65536)
                
                np_data = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(np_data, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    cv2.imshow("Chamada de Video (Recebendo)", frame)
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        self.parar()
                        break
                        
            except socket.timeout:
                continue
            except ConnectionResetError:
                # O Windows joga esse erro (10054) se o outro lado ainda não abriu a porta.
                # Como é UDP, apenas ignoramos e tentamos ler o próximo frame.
                continue
            except Exception as e:
                if self.rodando:
                    print(f"[Erro no Recebimento de Vídeo] {e}")
                    
        cv2.destroyAllWindows()

    def _enviar_video(self):
        cap = cv2.VideoCapture(0) 
        
        if not cap.isOpened():
            print("[Erro] Não foi possível acessar a webcam.")
            return

        while self.rodando:
            ret, frame = cap.read()
            if not ret:
                break
                
            frame = cv2.resize(frame, (320, 240))
            encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 50]
            _, buffer = cv2.imencode('.jpg', frame, encode_param)
            
            try:
                self.sock.sendto(buffer.tobytes(), (self.ip_destino, self.porta_destino))
            except ConnectionResetError:
                # Ignora o mesmo erro no envio
                continue
            except Exception as e:
                print(f"[Erro no Envio de Vídeo] {e}")
                break
                
        cap.release()

    def iniciar(self):
        self.rodando = True
        threading.Thread(target=self._receber_video, daemon=True).start()
        threading.Thread(target=self._enviar_video, daemon=True).start()
        print("\n\033[F\033[K[🎥] Chamada de vídeo iniciada! (Pressione 'q' na janela para encerrar)")

    def parar(self):
        self.rodando = False
        try:
            self.sock.close()
        except:
            pass