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
        with open(DB_PATH, 'r') as f: return json.load(f)
    return {"logins": [], "canais": ["geral", "tech"]}

db = carregar()
context = zmq.Context()
socket = context.socket(zmq.REP)
socket.connect("tcp://broker:5556")

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

    salvar(db)
    socket.send(res.SerializeToString())