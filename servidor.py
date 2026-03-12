import zmq
import msgpack
import time
import json
import os
import socket as sock

SERVER_ID = sock.gethostname()
DATA_DIR  = f"/data/{SERVER_ID}"
os.makedirs(DATA_DIR, exist_ok=True)

USERS_FILE    = f"{DATA_DIR}/users.json"
CHANNELS_FILE = f"{DATA_DIR}/channels.json"

ALLOWED_USERS = {"lucas", "joao", "maria", "carol", "artur"}

def load_json(path):
    if os.path.exists(path):
        with open(path) as f: return json.load(f)
    return {}

def save_json(path, data):
    with open(path, "w") as f: json.dump(data, f, indent=2)

context = zmq.Context()
socket  = context.socket(zmq.REP)
socket.connect("tcp://broker:5556")
print(f"[{SERVER_ID}] Servidor ativo...", flush=True)

while True:
    msg    = msgpack.unpackb(socket.recv(), raw=False)
    funcao = msg.get("funcao", "")
    dados  = msg.get("dados", {})
    resp   = {"timestamp": time.time()}

    if funcao == "login":
        username = dados.get("username", "").strip().lower() 
        users    = load_json(USERS_FILE)

        if not username:
            resp.update({"status": "erro", "mensagem": "Username vazio"})
        elif username not in ALLOWED_USERS:
            resp.update({"status": "erro", "mensagem": f"Usuario '{username}' nao autorizado. Validos: {', '.join(sorted(ALLOWED_USERS))}"})
        else:
            if username not in users: users[username] = []
            users[username].append({"login_at": time.time()})
            save_json(USERS_FILE, users)
            resp.update({"status": "ok", "mensagem": f"Login realizado: {username}"})

    elif funcao == "criar_canal":
        canal    = dados.get("canal", "").strip()
        username = dados.get("username", "")
        channels = load_json(CHANNELS_FILE)

        if not canal:
            resp.update({"status": "erro", "mensagem": "Nome do canal vazio"})
        elif not canal.replace("-", "").replace("_", "").isalnum():
            resp.update({"status": "erro", "mensagem": "Nome invalido (letras, numeros, - e _)"})
        elif canal in channels:
            resp.update({"status": "erro", "mensagem": f"Canal '{canal}' ja existe"})
        else:
            channels[canal] = {"criado_por": username, "criado_em": time.time()}
            save_json(CHANNELS_FILE, channels)
            resp.update({"status": "ok", "mensagem": f"Canal '{canal}' criado com sucesso"})

    elif funcao == "listar_canais":
        channels = load_json(CHANNELS_FILE)
        resp.update({"status": "ok", "canais": list(channels.keys())})

    else:
        resp.update({"status": "erro", "mensagem": f"Funcao desconhecida: {funcao}"})

    print(resp, flush=True)
    socket.send(msgpack.packb(resp, use_bin_type=True))