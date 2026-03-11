import zmq
import json 

context = zmq.Context()
socket = context.socket(zmq.REP)
socket.connect("tcp://broker:5556")

tarefas = list()

while True:
    msg = socket.recv_string()
    msg = json.loads(msg)

    funcao = msg.get("funcao", "")
    dados = msg.get("dados", "")

    if funcao == "criar":
        tarefas.append(dados)
        socket.send_string("ok")

    elif funcao == "deletar":
        if dados in tarefas:
            tarefas.remove(dados)
            socket.send_string("ok")
        else:
            socket.send_string("erro")

    elif funcao == "listar":
        socket.send_string(json.dumps(tarefas))

    else:
        socket.send_string("erro")

    print(tarefas, flush=True)