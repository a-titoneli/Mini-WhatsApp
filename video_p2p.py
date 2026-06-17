import cv2
import socket
import threading
import numpy as np

class VideoCall:
    def __init__(self, meu_ip, minha_porta_video, ip_destino, porta_destino, on_close=None):
        self.meu_ip = meu_ip
        self.minha_porta_video = minha_porta_video
        self.ip_destino = ip_destino
        self.porta_destino = porta_destino
        self.on_close = on_close  # Gatilho para avisar o encerramento ao app_p2p
        
        self.rodando = False
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', self.minha_porta_video))

    def _receber_video(self):
        print("\n\033[F\033[K[Vídeo] Aguardando conexão... (Pressione 'q' na janela de vídeo para encerrar)")
        tempo_sem_sinal = 0
        
        while self.rodando:
            try:
                self.sock.settimeout(0.5)
                data, addr = self.sock.recvfrom(65536)
                
                tempo_sem_sinal = 0 
                
                np_data = np.frombuffer(data, dtype=np.uint8)
                frame = cv2.imdecode(np_data, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    cv2.imshow("Chamada de Video (Recebendo)", frame)
                    
            except socket.timeout:
                tempo_sem_sinal += 0.5
                # Watchdog de segurança: se a ligação cair fisicamente, fecha em 5s
                if tempo_sem_sinal >= 5.0:
                    print("\n[Vídeo] A chamada foi encerrada (Conexão perdida).")
                    self.parar()
                    break
            except ConnectionResetError:
                pass
            except OSError:
                break
            except Exception:
                pass

            # Captura a tecla 'q' continuamente fora do bloco de receção
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("\n[Vídeo] Você encerrou a chamada.")
                self.parar()
                if self.on_close:
                    self.on_close()  # Dispara a notificação de rede
                break
                
        cv2.destroyAllWindows()

    def _enviar_video(self):
        cap = cv2.VideoCapture(0) 
        
        if not cap.isOpened():
            print("\n[Erro] Não foi possível acessar a webcam.")
            self.parar()
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
                pass
            except OSError:
                break
            except Exception:
                break
                
        cap.release()

    def iniciar(self):
        self.rodando = True
        threading.Thread(target=self._receber_video, daemon=True).start()
        threading.Thread(target=self._enviar_video, daemon=True).start()

    def parar(self):
        self.rodando = False
        try:
            self.sock.close()
        except:
            pass