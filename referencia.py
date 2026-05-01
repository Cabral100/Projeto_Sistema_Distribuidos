import zmq
import time
import threading
import mensagens_pb2

HEARTBEAT_TIMEOUT = 60
PORTA = 5559

servidores = {}
proximo_rank = [1]
lock = threading.Lock()

relogio_logico = [0]

def incrementar_relogio():
    relogio_logico[0] += 1
    return relogio_logico[0]

def atualizar_relogio(recebido):
    relogio_logico[0] = max(relogio_logico[0], recebido) + 1
    return relogio_logico[0]


def verificar_heartbeat():
    """Thread que remove servidores sem heartbeat recente."""
    while True:
        time.sleep(10)
        agora = time.time()
        with lock:
            expirados = [
                nome for nome, info in servidores.items()
                if (agora - info["last_heartbeat"]) > HEARTBEAT_TIMEOUT
            ]
            for nome in expirados:
                print(f"[REFERENCIA] Servidor '{nome}' removido por timeout de heartbeat.", flush=True)
                del servidores[nome]


def main():
    context = zmq.Context()
    socket = context.socket(zmq.REP)
    socket.bind(f"tcp://*:{PORTA}")

    print(f"[REFERENCIA] Servico de referencia online na porta {PORTA}...", flush=True)

    t = threading.Thread(target=verificar_heartbeat, daemon=True)
    t.start()

    while True:
        raw = socket.recv()
        req = mensagens_pb2.ReqReferencia()
        req.ParseFromString(raw)

        atualizar_relogio(req.relogio_logico)

        res = mensagens_pb2.ResReferencia()
        agora = time.time()

        if req.funcao == "rank":
            nome = req.nome
            with lock:
                if nome not in servidores:
                    rank = proximo_rank[0]
                    proximo_rank[0] += 1
                    servidores[nome] = {"rank": rank, "last_heartbeat": agora}
                    print(f"[REFERENCIA] Servidor '{nome}' registrado com rank {rank}.", flush=True)
                else:
                    rank = servidores[nome]["rank"]
                    servidores[nome]["last_heartbeat"] = agora

            incrementar_relogio()
            res.status = "ok"
            res.rank = rank
            res.relogio_logico = relogio_logico[0]

        elif req.funcao == "list":
            with lock:
                lista = list(servidores.items())

            incrementar_relogio()
            res.status = "ok"
            res.relogio_logico = relogio_logico[0]
            for nome, info in lista:
                srv = res.servidores.add()
                srv.nome = nome
                srv.rank = info["rank"]

            print(f"[REFERENCIA] Lista solicitada: {[(n, i['rank']) for n, i in lista]}", flush=True)

        elif req.funcao == "heartbeat":
            nome = req.nome
            with lock:
                if nome in servidores:
                    servidores[nome]["last_heartbeat"] = agora
                    rank = servidores[nome]["rank"]
                else:
                    rank = proximo_rank[0]
                    proximo_rank[0] += 1
                    servidores[nome] = {"rank": rank, "last_heartbeat": agora}
                    print(f"[REFERENCIA] Servidor '{nome}' re-registrado via heartbeat com rank {rank}.", flush=True)

            incrementar_relogio()
            res.status = "ok"
            res.relogio_logico = relogio_logico[0]
            print(f"[REFERENCIA] Heartbeat recebido de '{nome}'.", flush=True)

        else:
            incrementar_relogio()
            res.status = "erro"
            res.mensagem = f"Funcao desconhecida: {req.funcao}"
            res.relogio_logico = relogio_logico[0]

        socket.send(res.SerializeToString())


if __name__ == "__main__":
    main()
