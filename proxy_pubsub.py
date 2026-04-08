import zmq

context = zmq.Context()

xsub = context.socket(zmq.XSUB)
xsub.bind("tcp://*:5557")

xpub = context.socket(zmq.XPUB)
xpub.bind("tcp://*:5558")

print("[PROXY PUB/SUB] Online nas portas 5557 (XSUB) e 5558 (XPUB)...", flush=True)

zmq.proxy(xpub, xsub)

xsub.close()
xpub.close()
context.term()
