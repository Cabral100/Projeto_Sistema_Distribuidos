FROM python:3.11-slim
RUN apt-get update && apt-get install -y protobuf-compiler
WORKDIR /app
RUN pip install pyzmq protobuf
COPY mensagens.proto .
RUN protoc --python_out=. mensagens.proto
CMD ["python", "main.py"]