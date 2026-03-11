import zmq

context = zmq.Context()
poller = zmq.Poller()

frontend = context.socket(zmq.ROUTER)
frontend.bind("tcp://*:5555")

backend = context.socket(zmq.DEALER)
backend.bind("tcp://*:5556")

poller.register(frontend, zmq.POLLIN)
poller.register(backend, zmq.POLLIN)

print("Broker ativo (Portas 5555/5556)...")

while True:
    socks = dict(poller.poll())

    if socks.get(frontend) == zmq.POLLIN:
        frames = frontend.recv_multipart()
        backend.send_multipart(frames)

    if socks.get(backend) == zmq.POLLIN:
        frames = backend.recv_multipart()
        frontend.send_multipart(frames)