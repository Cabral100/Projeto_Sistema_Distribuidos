import zmq
import time
import json
import os
import mensagens_pb2

SERVER_NAME = os.getenv("SERVER_NAME", "servidor")
os.makedirs("/data", exist_ok=True)
DB_PATH = f"/data/{SERVER_NAME}_db.json"

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

print(f"[{SERVER_NAME}] Online...", flush=True)

while True:
    raw_msg = socket.recv()
    envelope = mensagens_pb2.Envelope()
    envelope.ParseFromString(raw_msg)

    res = mensagens_pb2.Resposta()
    res.timestamp = time.time()
    ts_formatado = time.strftime("%H:%M:%S")

    print(f"[{ts_formatado}] [{SERVER_NAME}] Req: {envelope.funcao} de {envelope.username}", flush=True)

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
        ts_recebimento = time.time()

        if canal not in db["canais"]:
            res.status, res.mensagem = "erro", f"Canal '{canal}' nao existe"
        else:
            publicacao_registro = {
                "canal": canal,
                "username": envelope.username,
                "mensagem": mensagem,
                "timestamp_envio": ts_envio,
                "timestamp_recebimento": ts_recebimento
            }
            db["publicacoes"].append(publicacao_registro)

            pub_msg = mensagens_pb2.Publicacao()
            pub_msg.canal = canal
            pub_msg.username = envelope.username
            pub_msg.mensagem = mensagem
            pub_msg.timestamp_envio = ts_envio
            pub_msg.timestamp_recebimento = ts_recebimento

            topico = canal.encode()
            pub_socket.send_multipart([topico, pub_msg.SerializeToString()])

            res.status = "ok"
            res.mensagem = f"Publicado no canal '{canal}'"
            print(f"[{ts_formatado}] [{SERVER_NAME}] Publicou em '{canal}': {mensagem}", flush=True)

    salvar(db)
    socket.send(res.SerializeToString())
