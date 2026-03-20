# Projeto Sistemas Distribuídos - Parte 1

## 📌 Introdução
Este projeto implementa um sistema de mensageria distribuída utilizando uma arquitetura **Broker-Intermediário**. O sistema permite que clientes (Bots) realizem login, criem canais de comunicação e listem canais ativos.

## 🛠️ Escolhas Técnicas

### 1. Linguagens e Comunicação
* **Java (Cliente):** Utilizado para os Bots, aproveitando a biblioteca `JeroMQ` para comunicação via sockets `REQ`.
* **Python (Broker e Servidor):** Utilizado para o Broker (`ROUTER/DEALER`) e Servidores (`REP`), aproveitando a simplicidade da biblioteca `pyzmq`.
* **ZeroMQ:** Escolhido como middleware de comunicação para garantir alta performance e escalabilidade através do padrão de mensagens assíncronas.

### 2. Serialização (Protocol Buffers)
Para cumprir o requisito de comunicação binária:
* Utilizamos **Google Protobuf** para definir um contrato rígido (`mensagens.proto`).
* Todas as mensagens incluem obrigatoriamente um campo `timestamp` (double) para rastreabilidade, conforme exigido.

### 3. Persistência de Dados
* **Formato:** JSON.
* **Isolamento:** Cada instância de servidor possui seu próprio volume de dados (ex: `/data/srv1`), garantindo que a persistência não seja compartilhada entre réplicas.
* **Dados Armazenados:** O sistema registra todos os logins (usuário + timestamp) e a lista de canais criados.

## 🚀 Como Executar
1. Certifique-se de ter os arquivos `mensagens.proto`, `cliente.java`, `servidor.py` e `broker.py` na estrutura correta.
2. Execute o comando:
   ```bash
   docker compose up --build