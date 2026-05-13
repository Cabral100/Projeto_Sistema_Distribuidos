import zmq
import time
import json
import os
import sqlite3
import threading
import mensagens_pb2

SERVER_NAME    = os.getenv("SERVER_NAME",   "servidor")
REFERENCIA_URL = os.getenv("REFERENCIA_URL", "tcp://referencia:5559")
PUBSUB_SUB_URL = os.getenv("PUBSUB_SUB_URL", "tcp://proxy_pubsub:5558")
S2S_PORT       = 5560
SYNC_INTERVALO = 15

os.makedirs("/data", exist_ok=True)
DB_PATH = f"/data/{SERVER_NAME}_db.sqlite"

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
# Persistencia - SQLite
# ---------------------------------------------------------------------------
_db_lock = threading.Lock()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS logins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        timestamp REAL
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS canais (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT UNIQUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS publicacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        canal TEXT,
        username TEXT,
        mensagem TEXT,
        timestamp_envio REAL,
        timestamp_recebimento REAL,
        relogio_logico INTEGER
    )""")
    # Canais padrao
    c.execute("INSERT OR IGNORE INTO canais (nome) VALUES ('geral')")
    c.execute("INSERT OR IGNORE INTO canais (nome) VALUES ('tech')")
    conn.commit()
    conn.close()

def db_listar_canais():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT nome FROM canais")
        canais = [row[0] for row in c.fetchall()]
        conn.close()
    return canais

def db_criar_canal(nome):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("INSERT INTO canais (nome) VALUES (?)", (nome,))
            conn.commit()
            criado = True
        except sqlite3.IntegrityError:
            criado = False
        conn.close()
    return criado

def db_canal_existe(nome):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT 1 FROM canais WHERE nome = ?", (nome,))
        existe = c.fetchone() is not None
        conn.close()
    return existe

def db_inserir_login(username, timestamp):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO logins (username, timestamp) VALUES (?, ?)", (username, timestamp))
        conn.commit()
        conn.close()

def db_inserir_publicacao(canal, username, mensagem, ts_envio, ts_recebimento, rl):
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""INSERT INTO publicacoes
            (canal, username, mensagem, timestamp_envio, timestamp_recebimento, relogio_logico)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (canal, username, mensagem, ts_envio, ts_recebimento, rl))
        conn.commit()
        conn.close()

def db_aplicar_replica(evento: mensagens_pb2.ReplicaEvento):
    """Recebe ReplicaEvento e persiste localmente - INSERT OR IGNORE para idempotencia."""
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            if evento.tipo_evento == "login":
                c.execute(
                    "INSERT OR IGNORE INTO logins (username, timestamp) VALUES (?, ?)",
                    (evento.username, evento.timestamp)
                )
            elif evento.tipo_evento == "canal":
                try:
                    c.execute("INSERT INTO canais (nome) VALUES (?)", (evento.canal,))
                except sqlite3.IntegrityError:
                    pass
            elif evento.tipo_evento == "mensagem":
                c.execute("""INSERT OR IGNORE INTO publicacoes
                    (canal, username, mensagem, timestamp_envio, timestamp_recebimento, relogio_logico)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (evento.canal, evento.username, evento.mensagem,
                     evento.timestamp, evento.timestamp, evento.relogio_logico))
            conn.commit()
        finally:
            conn.close()

# ---------------------------------------------------------------------------
# Sockets ZMQ
# ---------------------------------------------------------------------------
context = zmq.Context()

socket = context.socket(zmq.REP)
socket.connect("tcp://broker:5556")

pub_socket = context.socket(zmq.PUB)
pub_socket.connect("tcp://proxy_pubsub:5557")
_pub_lock = threading.Lock()

sub_socket = context.socket(zmq.SUB)
sub_socket.connect(PUBSUB_SUB_URL)
sub_socket.setsockopt_string(zmq.SUBSCRIBE, "servers")
# NOVO: inscreve no topico "replicas" para replicacao passiva por push
sub_socket.setsockopt_string(zmq.SUBSCRIBE, "replicas")

s2s_rep = context.socket(zmq.REP)
s2s_rep.bind(f"tcp://0.0.0.0:{S2S_PORT}")

poller = zmq.Poller()
poller.register(socket,     zmq.POLLIN)
poller.register(s2s_rep,    zmq.POLLIN)
poller.register(sub_socket, zmq.POLLIN)

# ---------------------------------------------------------------------------
# Helpers de socket temporario
# ---------------------------------------------------------------------------
def _criar_ref_socket():
    ref = context.socket(zmq.REQ)
    ref.setsockopt(zmq.RCVTIMEO, 5000)
    ref.setsockopt(zmq.SNDTIMEO, 5000)
    ref.setsockopt(zmq.LINGER, 0)
    ref.connect(REFERENCIA_URL)
    return ref

def _criar_s2s_socket(nome):
    sock = context.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, 2000)
    sock.setsockopt(zmq.SNDTIMEO, 2000)
    sock.setsockopt(zmq.LINGER, 0)
    sock.connect(f"tcp://{nome}:{S2S_PORT}")
    return sock

# ---------------------------------------------------------------------------
# Comunicacao com o servico de referencia
# ---------------------------------------------------------------------------
def obter_rank() -> int:
    ref = _criar_ref_socket()
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
    ref = _criar_ref_socket()
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
    ref = _criar_ref_socket()
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
        sock = _criar_s2s_socket(nome)
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
        with _pub_lock:
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

    sock = _criar_s2s_socket(coord)
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
        iniciar_eleicao()
    finally:
        sock.close()

# ---------------------------------------------------------------------------
# REPLICACAO PASSIVA POR PUSH
# Publica no topico "replicas" via PubSub - todos os outros servidores
# inscritos recebem e persistem localmente. Nao ha comunicacao direta
# entre servidores para replicar - usa a infraestrutura PubSub ja existente.
# ---------------------------------------------------------------------------
def publicar_replica(tipo_evento: str, username: str = "", canal: str = "",
                     mensagem: str = "", timestamp: float = None):
    """
    Publica um ReplicaEvento no topico 'replicas'.
    Os outros servidores recebem via thread_sub e aplicam no SQLite local.
    """
    if timestamp is None:
        timestamp = tempo_sincronizado()

    evento = mensagens_pb2.ReplicaEvento()
    evento.servidor_origem = SERVER_NAME
    evento.tipo_evento     = tipo_evento
    evento.username        = username
    evento.canal           = canal
    evento.mensagem        = mensagem
    evento.timestamp       = timestamp
    evento.relogio_logico  = rl_enviar()

    with _pub_lock:
        pub_socket.send_multipart([b"replicas", evento.SerializeToString()])

# ---------------------------------------------------------------------------
# Thread S2S - apenas eleicao e sync (replicacao foi para PubSub)
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
            try:
                s2s_rep.send(mensagens_pb2.ResS2S().SerializeToString())
            except Exception:
                pass
            continue

        rl_receber(req.relogio_logico)
        res = mensagens_pb2.ResS2S()
        res.relogio_logico = rl_enviar()

        if req.funcao == "eleicao":
            res.ok = True
            try:
                s2s_rep.send(res.SerializeToString())
            except Exception as e:
                print(f"[{SERVER_NAME}] Erro ao responder eleicao: {e}", flush=True)
            threading.Thread(target=iniciar_eleicao, daemon=True).start()

        elif req.funcao == "sync":
            res.ok = True
            res.timestamp = int(tempo_sincronizado())
            try:
                s2s_rep.send(res.SerializeToString())
            except Exception as e:
                print(f"[{SERVER_NAME}] Erro ao responder sync: {e}", flush=True)

        else:
            res.ok = False
            try:
                s2s_rep.send(res.SerializeToString())
            except Exception as e:
                print(f"[{SERVER_NAME}] Erro ao responder funcao desconhecida: {e}", flush=True)

# ---------------------------------------------------------------------------
# Thread SUB - escuta "servers" (coordenador) e "replicas" (replicacao passiva)
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

            elif topico == b"replicas":
                evento = mensagens_pb2.ReplicaEvento()
                evento.ParseFromString(payload)
                # Ignora replicas geradas pelo proprio servidor
                if evento.servidor_origem == SERVER_NAME:
                    continue
                rl_receber(evento.relogio_logico)
                db_aplicar_replica(evento)
                print(f"[{SERVER_NAME}] Replica recebida: "
                      f"tipo={evento.tipo_evento} "
                      f"canal={evento.canal} "
                      f"user={evento.username} "
                      f"origem={evento.servidor_origem}", flush=True)

        except Exception as e:
            print(f"[{SERVER_NAME}] Erro no sub: {e}", flush=True)

# ---------------------------------------------------------------------------
# Inicializacao
# ---------------------------------------------------------------------------
init_db()
time.sleep(2)
_meu_rank = obter_rank()
print(f"[{SERVER_NAME}] Online (rank={_meu_rank})...", flush=True)

threading.Thread(target=thread_s2s, daemon=True).start()
threading.Thread(target=thread_sub, daemon=True).start()

time.sleep(1)
threading.Thread(target=iniciar_eleicao, daemon=True).start()

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
            db_inserir_login(envelope.username, envelope.timestamp)
            # Replica passiva por push
            publicar_replica("login", username=envelope.username,
                             timestamp=envelope.timestamp)
            res.status  = "ok"
            res.mensagem = f"Login aceito no {SERVER_NAME}"

        elif envelope.funcao == "criar_canal":
            criado = db_criar_canal(envelope.parametro)
            if criado:
                publicar_replica("canal", canal=envelope.parametro)
                res.status  = "ok"
                res.mensagem = "Canal criado"
            else:
                res.status  = "erro"
                res.mensagem = "Canal ja existe"

        elif envelope.funcao == "listar_canais":
            canais = db_listar_canais()
            res.status = "ok"
            res.canais.extend(canais)

        elif envelope.funcao == "publicar_canal":
            canal        = envelope.parametro
            mensagem_txt = envelope.mensagem
            ts_envio     = envelope.timestamp
            ts_receb     = tempo_sincronizado()

            if not db_canal_existe(canal):
                res.status  = "erro"
                res.mensagem = f"Canal '{canal}' nao existe"
            else:
                db_inserir_publicacao(canal, envelope.username, mensagem_txt,
                                      ts_envio, ts_receb, _relogio_logico)

                # Pub/Sub para clientes inscritos
                pub_msg = mensagens_pb2.Publicacao()
                pub_msg.canal               = canal
                pub_msg.username            = envelope.username
                pub_msg.mensagem            = mensagem_txt
                pub_msg.timestamp_envio     = ts_envio
                pub_msg.timestamp_recebimento = ts_receb
                pub_msg.relogio_logico      = _relogio_logico
                with _pub_lock:
                    pub_socket.send_multipart([canal.encode(), pub_msg.SerializeToString()])

                # Replica passiva por push (nao bloqueia a resposta ao cliente)
                threading.Thread(
                    target=publicar_replica,
                    args=("mensagem",),
                    kwargs={
                        "username":  envelope.username,
                        "canal":     canal,
                        "mensagem":  mensagem_txt,
                        "timestamp": ts_envio,
                    },
                    daemon=True
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