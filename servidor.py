import zmq
import time
import json
import os
import threading
import mensagens_pb2

SERVER_NAME = os.getenv("SERVER_NAME", "servidor")
REFERENCIA_URL = os.getenv("REFERENCIA_URL", "tcp://referencia:5559")
HEARTBEAT_INTERVALO = 10 

os.makedirs("/data", exist_ok=True)
DB_PATH = f"/data/{SERVER_NAME}_db.json"

_rl_lock = threading.Lock()
_relogio_logico = 0

def rl_enviar():
    """Incrementa o relógio antes de enviar uma mensagem e retorna o valor."""
    global _relogio_logico
    with _rl_lock:
        _relogio_logico += 1
        return _relogio_logico

def rl_receber(recebido: int) -> int:
    """Atualiza o relógio ao receber uma mensagem e retorna o novo valor."""
    global _relogio_logico
    with _rl_lock:
        _relogio_logico = max(_relogio_logico, recebido) + 1
        return _relogio_logico

_offset = 0.0         
_offset_lock = threading.Lock()

def tempo_sincronizado() -> float:
    with _offset_lock:
        return time.time() + _offset

def salvar(db):
    with open(DB_PATH, 'w') as f:
        json.dump(db, f, indent=4)

def carregar():
    if os.path.exists(DB_PATH):
        with open(DB_PATH, 'r') as f:
            return json.load(f)
    return {"logins": [], "canais": ["geral", "tech"], "publicacoes": []}

db = carregar()
if "publicacoes" not in db:
    db["publicacoes"] = []

context = zmq.Context()

socket = context.socket(zmq.REP)
socket.connect("tcp://broker:5556")

pub_socket = context.socket(zmq.PUB)
pub_socket.connect("tcp://proxy_pubsub:5557")

def obter_rank():
    ref = context.socket(zmq.REQ)
    ref.setsockopt(zmq.RCVTIMEO, 5000)
    ref.connect(REFERENCIA_URL)
    try:
        req = mensagens_pb2.ReqReferencia()
        req.funcao = "rank"
        req.nome = SERVER_NAME
        req.relogio_logico = rl_enviar()
        ref.send(req.SerializeToString())
        raw = ref.recv()
        res = mensagens_pb2.ResReferencia()
        res.ParseFromString(raw)
        rl_receber(res.relogio_logico)
        print(f"[{SERVER_NAME}] Rank obtido: {res.rank}", flush=True)
        return res.rank
    except Exception as e:
        print(f"[{SERVER_NAME}] Erro ao obter rank: {e}", flush=True)
        return -1
    finally:
        ref.close()

_msg_count = 0
_rank = -1

def enviar_heartbeat():
    """Envia heartbeat ao serviço de referência e sincroniza o relógio físico."""
    global _offset
    ref = context.socket(zmq.REQ)
    ref.setsockopt(zmq.RCVTIMEO, 5000)
    ref.connect(REFERENCIA_URL)
    try:
        t_antes = time.time()

        req = mensagens_pb2.ReqReferencia()
        req.funcao = "heartbeat"
        req.nome = SERVER_NAME
        req.relogio_logico = rl_enviar()
        ref.send(req.SerializeToString())

        raw = ref.recv()
        t_depois = time.time()

        res = mensagens_pb2.ResReferencia()
        res.ParseFromString(raw)
        rl_receber(res.relogio_logico)

        rtt = t_depois - t_antes
        t_estimado = res.timestamp + rtt / 2
        novo_offset = t_estimado - t_depois

        with _offset_lock:
            _offset = novo_offset

        print(
            f"[{SERVER_NAME}] Heartbeat OK | RTT={rtt*1000:.1f}ms | "
            f"offset={novo_offset*1000:.1f}ms",
            flush=True
        )
    except Exception as e:
        print(f"[{SERVER_NAME}] Erro no heartbeat: {e}", flush=True)
    finally:
        ref.close()


time.sleep(2)
_rank = obter_rank()

print(f"[{SERVER_NAME}] Online (rank={_rank})...", flush=True)

while True:
    raw_msg = socket.recv()
    envelope = mensagens_pb2.Envelope()
    envelope.ParseFromString(raw_msg)

    rl_receber(envelope.relogio_logico)

    res = mensagens_pb2.Resposta()
    res.timestamp = tempo_sincronizado()
    ts_formatado = time.strftime("%H:%M:%S")

    print(
        f"[{ts_formatado}] [{SERVER_NAME}] Req: {envelope.funcao} de {envelope.username} "
        f"[RL_cliente={envelope.relogio_logico}, RL_servidor={_relogio_logico}]",
        flush=True
    )

    if envelope.funcao == "login":
        db["logins"].append({"user": envelope.username, "ts": envelope.timestamp})
        res.status, res.mensagem = "ok", f"Login aceito no {SERVER_NAME}"

    elif envelope.funcao == "criar_canal":
        if envelope.parametro not in db["canais"]:
            db["canais"].append(envelope.parametro)
            res.status, res.mensagem = "ok", "Canal criado"
        else:
            res.status, res.mensagem = "erro", "Canal ja existe"

    elif envelope.funcao == "listar_canais":
        res.status = "ok"
        res.canais.extend(db["canais"])

    elif envelope.funcao == "publicar_canal":
        canal = envelope.parametro
        mensagem = envelope.mensagem
        ts_envio = envelope.timestamp
        ts_recebimento = tempo_sincronizado()

        if canal not in db["canais"]:
            res.status, res.mensagem = "erro", f"Canal '{canal}' nao existe"
        else:
            publicacao_registro = {
                "canal": canal,
                "username": envelope.username,
                "mensagem": mensagem,
                "timestamp_envio": ts_envio,
                "timestamp_recebimento": ts_recebimento,
                "relogio_logico": _relogio_logico,
            }
            db["publicacoes"].append(publicacao_registro)

            pub_msg = mensagens_pb2.Publicacao()
            pub_msg.canal = canal
            pub_msg.username = envelope.username
            pub_msg.mensagem = mensagem
            pub_msg.timestamp_envio = ts_envio
            pub_msg.timestamp_recebimento = ts_recebimento
            pub_msg.relogio_logico = _relogio_logico

            topico = canal.encode()
            pub_socket.send_multipart([topico, pub_msg.SerializeToString()])

            res.status = "ok"
            res.mensagem = f"Publicado no canal '{canal}'"
            print(
                f"[{ts_formatado}] [{SERVER_NAME}] Publicou em '{canal}': {mensagem}",
                flush=True
            )

    res.relogio_logico = rl_enviar()

    salvar(db)
    socket.send(res.SerializeToString())

    _msg_count += 1
    if _msg_count % HEARTBEAT_INTERVALO == 0:
        threading.Thread(target=enviar_heartbeat, daemon=True).start()
