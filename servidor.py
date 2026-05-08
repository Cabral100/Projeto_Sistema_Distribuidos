import zmq
import time
import json
import os
import threading
import mensagens_pb2

SERVER_NAME    = os.getenv("SERVER_NAME",   "servidor")
REFERENCIA_URL = os.getenv("REFERENCIA_URL", "tcp://referencia:5559")
PUBSUB_SUB_URL = os.getenv("PUBSUB_SUB_URL", "tcp://proxy_pubsub:5558")
S2S_PORT       = 5560
SYNC_INTERVALO = 15

os.makedirs("/data", exist_ok=True)
DB_PATH = f"/data/{SERVER_NAME}_db.json"

# ---------------------------------------------------------------------------
# Relogio logico de Lamport
# ---------------------------------------------------------------------------
_rl_lock = threading.Lock()
_relogio_logico = 0

def rl_enviar():
    global _relogio_logico
    with _rl_lock:
        _relogio_logico += 1
        return _relogio_logico

def rl_receber(recebido: int) -> int:
    global _relogio_logico
    with _rl_lock:
        _relogio_logico = max(_relogio_logico, recebido) + 1
        return _relogio_logico

# ---------------------------------------------------------------------------
# Relogio fisico sincronizado
# ---------------------------------------------------------------------------
_offset = 0
_offset_lock = threading.Lock()

def tempo_sincronizado() -> float:
    with _offset_lock:
        return time.time() + _offset

def aplicar_offset(novo_offset: int):
    global _offset
    with _offset_lock:
        _offset = novo_offset
    print(f"[{SERVER_NAME}] Relogio ajustado: offset={novo_offset}s", flush=True)

# ---------------------------------------------------------------------------
# Eleicao / coordenador
# ---------------------------------------------------------------------------
_coord_lock = threading.Lock()
_coordenador = None
_meu_rank    = -1
_eleicao_em_andamento = False

def get_coordenador():
    with _coord_lock:
        return _coordenador

def set_coordenador(nome):
    global _coordenador, _eleicao_em_andamento
    with _coord_lock:
        _coordenador = nome
        _eleicao_em_andamento = False
    print(f"[{SERVER_NAME}] Coordenador: {nome}", flush=True)

def sou_coordenador():
    return get_coordenador() == SERVER_NAME

# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
_db_lock = threading.Lock()

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

# ---------------------------------------------------------------------------
# Sockets ZMQ
# ---------------------------------------------------------------------------
context = zmq.Context()

socket = context.socket(zmq.REP)
socket.connect("tcp://broker:5556")

pub_socket = context.socket(zmq.PUB)
pub_socket.connect("tcp://proxy_pubsub:5557")

sub_socket = context.socket(zmq.SUB)
sub_socket.connect(PUBSUB_SUB_URL)
sub_socket.setsockopt_string(zmq.SUBSCRIBE, "servers")

s2s_rep = context.socket(zmq.REP)
s2s_rep.bind(f"tcp://0.0.0.0:{S2S_PORT}")

poller = zmq.Poller()
poller.register(socket,     zmq.POLLIN)
poller.register(s2s_rep,    zmq.POLLIN)
poller.register(sub_socket, zmq.POLLIN)

# ---------------------------------------------------------------------------
# Comunicacao com o servico de referencia
# ---------------------------------------------------------------------------
def obter_rank() -> int:
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

def obter_lista_servidores():
    ref = context.socket(zmq.REQ)
    ref.setsockopt(zmq.RCVTIMEO, 5000)
    ref.connect(REFERENCIA_URL)
    try:
        req = mensagens_pb2.ReqReferencia()
        req.funcao = "list"
        req.nome = SERVER_NAME
        req.relogio_logico = rl_enviar()
        ref.send(req.SerializeToString())
        raw = ref.recv()
        res = mensagens_pb2.ResReferencia()
        res.ParseFromString(raw)
        rl_receber(res.relogio_logico)
        return list(res.servidores)
    except Exception as e:
        print(f"[{SERVER_NAME}] Erro ao obter lista: {e}", flush=True)
        return []
    finally:
        ref.close()

def enviar_heartbeat():
    ref = context.socket(zmq.REQ)
    ref.setsockopt(zmq.RCVTIMEO, 5000)
    ref.connect(REFERENCIA_URL)
    try:
        req = mensagens_pb2.ReqReferencia()
        req.funcao = "heartbeat"
        req.nome = SERVER_NAME
        req.relogio_logico = rl_enviar()
        ref.send(req.SerializeToString())
        raw = ref.recv()
        res = mensagens_pb2.ResReferencia()
        res.ParseFromString(raw)
        rl_receber(res.relogio_logico)
        print(f"[{SERVER_NAME}] Heartbeat OK", flush=True)
    except Exception as e:
        print(f"[{SERVER_NAME}] Erro no heartbeat: {e}", flush=True)
    finally:
        ref.close()

# ---------------------------------------------------------------------------
# Eleicao - Algoritmo Bully
# ---------------------------------------------------------------------------
def iniciar_eleicao():
    global _eleicao_em_andamento
    with _coord_lock:
        if _eleicao_em_andamento:
            return
        _eleicao_em_andamento = True

    print(f"[{SERVER_NAME}] Iniciando eleicao (rank={_meu_rank})...", flush=True)

    servidores = obter_lista_servidores()
    candidatos_superiores = [s.nome for s in servidores if s.rank > _meu_rank and s.nome != SERVER_NAME]

    recebeu_ok = False
    for nome in candidatos_superiores:
        sock = context.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 1000)
        sock.connect(f"tcp://{nome}:{S2S_PORT}")
        try:
            req = mensagens_pb2.ReqS2S()
            req.funcao = "eleicao"
            req.relogio_logico = rl_enviar()
            sock.send(req.SerializeToString())
            raw = sock.recv()
            res = mensagens_pb2.ResS2S()
            res.ParseFromString(raw)
            rl_receber(res.relogio_logico)
            if res.ok:
                recebeu_ok = True
        except Exception:
            pass
        finally:
            sock.close()

    if not recebeu_ok:
        set_coordenador(SERVER_NAME)
        pub_msg = mensagens_pb2.Publicacao()
        pub_msg.canal = "servers"
        pub_msg.username = "system"
        pub_msg.mensagem = SERVER_NAME
        pub_msg.timestamp_envio = tempo_sincronizado()
        pub_msg.timestamp_recebimento = tempo_sincronizado()
        pub_msg.relogio_logico = rl_enviar()
        pub_socket.send_multipart([b"servers", pub_msg.SerializeToString()])
        print(f"[{SERVER_NAME}] Eleito coordenador! Anunciado no topico 'servers'.", flush=True)
    else:
        with _coord_lock:
            _eleicao_em_andamento = False

# ---------------------------------------------------------------------------
# Sincronizacao de relogio - Algoritmo de Berkeley
# ---------------------------------------------------------------------------
def sincronizar_relogio():
    coord = get_coordenador()
    if coord is None:
        iniciar_eleicao()
        return
    if coord == SERVER_NAME:
        return

    sock = context.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 2000)
    sock.connect(f"tcp://{coord}:{S2S_PORT}")
    try:
        req = mensagens_pb2.ReqS2S()
        req.funcao = "sync"
        req.relogio_logico = rl_enviar()
        sock.send(req.SerializeToString())
        raw = sock.recv()
        res = mensagens_pb2.ResS2S()
        res.ParseFromString(raw)
        rl_receber(res.relogio_logico)
        novo_offset = res.timestamp - int(time.time())
        aplicar_offset(novo_offset)
        print(f"[{SERVER_NAME}] Sync OK | coordenador={coord} | offset={novo_offset}s", flush=True)
    except Exception as e:
        print(f"[{SERVER_NAME}] Coordenador {coord} nao respondeu ao sync: {e}", flush=True)
        sock.close()
        iniciar_eleicao()
        return
    finally:
        try:
            sock.close()
        except Exception:
            pass

# ---------------------------------------------------------------------------
# REPLICACAO - Replicacao Ativa (Active Replication)
# ---------------------------------------------------------------------------

def _chave_pub(pub: dict) -> tuple:
    """Chave de deduplicacao: (canal, username, mensagem, timestamp_envio)."""
    return (pub["canal"], pub["username"], pub["mensagem"], pub["timestamp_envio"])

def replicar_publicacao(pub: dict):
    """
    Envia a publicacao a todos os outros servidores ativos via S2S REQ/REP.
    A chamada e feita em thread separada para nao bloquear a resposta ao cliente.
    Servidores que nao respondem sao ignorados - receberao a publicacao via snapshot
    quando voltarem ao cluster.
    """
    servidores = obter_lista_servidores()
    outros = [s.nome for s in servidores if s.nome != SERVER_NAME]

    for nome in outros:
        sock = context.socket(zmq.REQ)
        sock.setsockopt(zmq.RCVTIMEO, 2000)
        sock.connect(f"tcp://{nome}:{S2S_PORT}")
        try:
            req = mensagens_pb2.ReqS2S()
            req.funcao               = "replicar"
            req.relogio_logico       = rl_enviar()
            req.canal                = pub["canal"]
            req.username             = pub["username"]
            req.mensagem             = pub["mensagem"]
            req.timestamp_envio      = pub["timestamp_envio"]
            req.timestamp_recebimento = pub["timestamp_recebimento"]
            sock.send(req.SerializeToString())
            raw = sock.recv()
            res = mensagens_pb2.ResS2S()
            res.ParseFromString(raw)
            rl_receber(res.relogio_logico)
            if res.ok:
                print(f"[{SERVER_NAME}] Replicado para {nome}: canal={pub['canal']}", flush=True)
        except Exception as e:
            print(f"[{SERVER_NAME}] Falha ao replicar para {nome}: {e}", flush=True)
        finally:
            sock.close()

def sincronizar_snapshot_com(nome: str):
    """
    Solicita o snapshot completo do banco de dados de outro servidor.
    Usado na inicializacao para obter o estado atual do cluster.
    """
    sock = context.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 5000)
    sock.connect(f"tcp://{nome}:{S2S_PORT}")
    try:
        req = mensagens_pb2.ReqS2S()
        req.funcao = "snapshot"
        req.relogio_logico = rl_enviar()
        sock.send(req.SerializeToString())
        raw = sock.recv()
        res = mensagens_pb2.ResS2S()
        res.ParseFromString(raw)
        rl_receber(res.relogio_logico)
        if res.ok and res.snapshot_json:
            dados = json.loads(res.snapshot_json)
            print(f"[{SERVER_NAME}] Snapshot recebido de {nome}: "
                  f"{len(dados.get('publicacoes', []))} publicacoes", flush=True)
            return dados
    except Exception as e:
        print(f"[{SERVER_NAME}] Falha ao obter snapshot de {nome}: {e}", flush=True)
    finally:
        sock.close()
    return None

def aplicar_snapshot(dados_remotos: dict):
    """
    Mescla o snapshot remoto no banco local usando deduplicacao por chave.
    Mantem publicacoes locais que o remoto nao tem e adiciona as que faltam.
    """
    global db
    with _db_lock:
        chaves_locais = {_chave_pub(p) for p in db.get("publicacoes", [])}

        novas = [
            p for p in dados_remotos.get("publicacoes", [])
            if _chave_pub(p) not in chaves_locais
        ]
        if novas:
            db["publicacoes"].extend(novas)
            print(f"[{SERVER_NAME}] Snapshot aplicado: +{len(novas)} publicacoes novas", flush=True)

        canais_remotos = set(dados_remotos.get("canais", []))
        canais_locais  = set(db.get("canais", []))
        novos_canais   = canais_remotos - canais_locais
        if novos_canais:
            db["canais"].extend(list(novos_canais))
            print(f"[{SERVER_NAME}] Canais adicionados: {novos_canais}", flush=True)

        salvar(db)

def inicializar_replica():
    """
    Executado na inicializacao: tenta obter o snapshot de cada servidor ativo
    e mescla o primeiro que responder com sucesso.
    """
    print(f"[{SERVER_NAME}] Iniciando sincronizacao de snapshot...", flush=True)
    servidores = obter_lista_servidores()
    outros = [s.nome for s in servidores if s.nome != SERVER_NAME]

    for nome in outros:
        dados = sincronizar_snapshot_com(nome)
        if dados:
            aplicar_snapshot(dados)
            print(f"[{SERVER_NAME}] Replica inicializada a partir de {nome}.", flush=True)
            return

    print(f"[{SERVER_NAME}] Nenhum servidor disponivel para snapshot. Iniciando com dados locais.", flush=True)

# ---------------------------------------------------------------------------
# Thread S2S - atende chamadas de outros servidores
# ---------------------------------------------------------------------------
def thread_s2s():
    while True:
        try:
            raw = s2s_rep.recv()
        except Exception:
            continue

        req = mensagens_pb2.ReqS2S()
        try:
            req.ParseFromString(raw)
        except Exception:
            s2s_rep.send(mensagens_pb2.ResS2S().SerializeToString())
            continue

        rl_receber(req.relogio_logico)

        res = mensagens_pb2.ResS2S()
        res.relogio_logico = rl_enviar()

        if req.funcao == "eleicao":
            res.ok = True
            s2s_rep.send(res.SerializeToString())
            threading.Thread(target=iniciar_eleicao, daemon=True).start()

        elif req.funcao == "sync":
            res.ok = True
            res.timestamp = int(tempo_sincronizado())
            s2s_rep.send(res.SerializeToString())

        elif req.funcao == "replicar":
            # Recebe uma publicacao replicada de outro servidor
            pub = {
                "canal":                req.canal,
                "username":             req.username,
                "mensagem":             req.mensagem,
                "timestamp_envio":      req.timestamp_envio,
                "timestamp_recebimento": req.timestamp_recebimento,
                "relogio_logico":       req.relogio_logico,
            }
            with _db_lock:
                chaves_locais = {_chave_pub(p) for p in db.get("publicacoes", [])}
                if _chave_pub(pub) not in chaves_locais:
                    db["publicacoes"].append(pub)
                    salvar(db)
                    print(f"[{SERVER_NAME}] Replica recebida: canal={pub['canal']} "
                          f"user={pub['username']}", flush=True)
                else:
                    print(f"[{SERVER_NAME}] Replica duplicada ignorada: canal={pub['canal']}", flush=True)
            res.ok = True
            s2s_rep.send(res.SerializeToString())

        elif req.funcao == "snapshot":
            # Envia o estado completo do banco local ao servidor solicitante
            with _db_lock:
                snapshot = json.dumps(db)
            res.ok = True
            res.snapshot_json = snapshot
            s2s_rep.send(res.SerializeToString())
            print(f"[{SERVER_NAME}] Snapshot enviado.", flush=True)

        else:
            res.ok = False
            s2s_rep.send(res.SerializeToString())

# ---------------------------------------------------------------------------
# Thread SUB - escuta topico 'servers' para atualizar coordenador
# ---------------------------------------------------------------------------
def thread_sub():
    while True:
        try:
            topico, payload = sub_socket.recv_multipart()
            if topico == b"servers":
                pub_msg = mensagens_pb2.Publicacao()
                pub_msg.ParseFromString(payload)
                novo_coord = pub_msg.mensagem
                if novo_coord and get_coordenador() != novo_coord:
                    set_coordenador(novo_coord)
        except Exception as e:
            print(f"[{SERVER_NAME}] Erro no sub: {e}", flush=True)

# ---------------------------------------------------------------------------
# Inicializacao
# ---------------------------------------------------------------------------
time.sleep(2)
_meu_rank = obter_rank()
print(f"[{SERVER_NAME}] Online (rank={_meu_rank})...", flush=True)

threading.Thread(target=thread_s2s,  daemon=True).start()
threading.Thread(target=thread_sub,  daemon=True).start()

time.sleep(3)
# Sincroniza o snapshot antes de entrar em operacao
threading.Thread(target=inicializar_replica, daemon=True).start()
threading.Thread(target=iniciar_eleicao,     daemon=True).start()

_msg_count = 0

# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------
while True:
    socks = dict(poller.poll(1000))

    if socket in socks and socks[socket] == zmq.POLLIN:
        raw_msg = socket.recv()
        envelope = mensagens_pb2.Envelope()
        envelope.ParseFromString(raw_msg)

        rl_receber(envelope.relogio_logico)

        res = mensagens_pb2.Resposta()
        res.timestamp = tempo_sincronizado()
        ts_formatado = time.strftime("%H:%M:%S")
        coord_atual  = get_coordenador() or "?"

        print(
            f"[{ts_formatado}] [{SERVER_NAME}] Req: {envelope.funcao} de {envelope.username} "
            f"[RL={_relogio_logico}, coord={coord_atual}]",
            flush=True
        )

        if envelope.funcao == "login":
            with _db_lock:
                db["logins"].append({"user": envelope.username, "ts": envelope.timestamp})
                salvar(db)
            res.status, res.mensagem = "ok", f"Login aceito no {SERVER_NAME}"

        elif envelope.funcao == "criar_canal":
            with _db_lock:
                if envelope.parametro not in db["canais"]:
                    db["canais"].append(envelope.parametro)
                    salvar(db)
                    res.status, res.mensagem = "ok", "Canal criado"
                else:
                    res.status, res.mensagem = "erro", "Canal ja existe"

        elif envelope.funcao == "listar_canais":
            with _db_lock:
                canais = list(db["canais"])
            res.status = "ok"
            res.canais.extend(canais)

        elif envelope.funcao == "publicar_canal":
            canal         = envelope.parametro
            mensagem_txt  = envelope.mensagem
            ts_envio      = envelope.timestamp
            ts_recebimento = tempo_sincronizado()

            with _db_lock:
                canal_existe = canal in db["canais"]

            if not canal_existe:
                res.status, res.mensagem = "erro", f"Canal '{canal}' nao existe"
            else:
                pub = {
                    "canal":                canal,
                    "username":             envelope.username,
                    "mensagem":             mensagem_txt,
                    "timestamp_envio":      ts_envio,
                    "timestamp_recebimento": ts_recebimento,
                    "relogio_logico":       _relogio_logico,
                }
                with _db_lock:
                    db["publicacoes"].append(pub)
                    salvar(db)

                # Publica via Pub/Sub para clientes inscritos
                pub_msg = mensagens_pb2.Publicacao()
                pub_msg.canal               = canal
                pub_msg.username            = envelope.username
                pub_msg.mensagem            = mensagem_txt
                pub_msg.timestamp_envio     = ts_envio
                pub_msg.timestamp_recebimento = ts_recebimento
                pub_msg.relogio_logico      = _relogio_logico
                pub_socket.send_multipart([canal.encode(), pub_msg.SerializeToString()])

                # Replica para os demais servidores em background
                threading.Thread(
                    target=replicar_publicacao, args=(pub,), daemon=True
                ).start()

                res.status   = "ok"
                res.mensagem = f"Publicado no canal '{canal}'"
                print(f"[{ts_formatado}] [{SERVER_NAME}] Publicou em '{canal}': {mensagem_txt}", flush=True)

        res.relogio_logico = rl_enviar()
        socket.send(res.SerializeToString())

        _msg_count += 1
        if _msg_count % SYNC_INTERVALO == 0:
            threading.Thread(target=enviar_heartbeat,    daemon=True).start()
            threading.Thread(target=sincronizar_relogio, daemon=True).start()
