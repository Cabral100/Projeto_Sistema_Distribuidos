# Projeto Sistemas Distribuídos

## 📌 Visão Geral

Sistema de mensageria distribuída onde bots (clientes Java) se comunicam com servidores Python através de um broker intermediário. O sistema suporta login, criação de canais e publicação de mensagens em tempo real.

**Tecnologias utilizadas:**
- **Java** — clientes/bots com `JeroMQ`
- **Python** — broker, servidor e proxy com `pyzmq`
- **ZeroMQ** — middleware de comunicação assíncrona
- **Protocol Buffers (Protobuf)** — serialização binária de todas as mensagens
- **Docker / Docker Compose** — orquestração dos serviços

---

## Parte 1 — Request-Reply com Broker

### O que foi implementado

Os bots conseguem se conectar ao sistema, fazer login, criar canais e listar os canais existentes. Toda a comunicação passa por um broker intermediário que distribui as requisições entre os servidores disponíveis.

### Troca de mensagens

O padrão utilizado é **Req-Rep** com broker `ROUTER/DEALER`:

- O cliente usa socket `REQ` e envia um `Envelope` Protobuf contendo: `funcao`, `username`, `parametro` e `timestamp` de envio.
- O broker (`ROUTER` na porta `5555` para clientes, `DEALER` na porta `5556` para servidores) roteia a requisição para um servidor disponível.
- O servidor responde com uma `Resposta` Protobuf contendo: `status`, `mensagem`, lista de `canais` e `timestamp`.

Todas as mensagens obrigatoriamente incluem o `timestamp` do momento do envio para rastreabilidade.

### Armazenamento

Cada servidor persiste seus dados em `/data/{SERVER_NAME}_db.json` com:
- `logins` — histórico de autenticações (usuário + timestamp)
- `canais` — lista de canais criados

Cada instância de servidor possui seu próprio volume isolado (`/data/srv1`, `/data/srv2`).

---

## Parte 2 — Publisher-Subscriber para publicação em canais

### O que foi implementado

Os bots agora podem publicar mensagens em canais e receber em tempo real as mensagens dos canais nos quais estão inscritos, usando um segundo padrão de comunicação paralelo ao Req-Rep.

### Troca de mensagens

Foi adicionado um **proxy Pub/Sub separado** do broker Req-Rep, conforme requisito:

- Porta `5557` como `XSUB` — recebe publicações dos servidores
- Porta `5558` como `XPUB` — distribui mensagens para os clientes inscritos

O fluxo de uma publicação funciona assim:
1. O bot envia uma requisição `publicar_canal` ao servidor via Req-Rep (com `canal`, `mensagem` e `timestamp`).
2. O servidor publica a mensagem no proxy Pub/Sub usando o **nome do canal como tópico**.
3. O servidor retorna `ok/erro` ao bot.
4. Todos os bots inscritos naquele canal recebem a mensagem via Pub/Sub.

A inscrição em canais é feita exclusivamente no cliente: cada bot mantém uma `AssinanteThread` dedicada com socket `SUB` conectado ao proxy, podendo se inscrever em múltiplos tópicos na mesma conexão. Ao receber uma mensagem, exibe: canal, remetente, conteúdo, timestamp de envio e timestamp de recebimento.

Todas as mensagens (tanto a requisição ao servidor quanto a publicação no canal) contêm o `timestamp` de envio.

### Armazenamento

O servidor passou a persistir também as publicações no mesmo arquivo `/data/{SERVER_NAME}_db.json`, adicionando o campo:
- `publicacoes` — lista de todas as mensagens publicadas, contendo: canal, usuário, mensagem, `timestamp_envio` (do cliente) e `timestamp_recebimento` (do servidor)

Isso permite recuperar o histórico completo de todas as publicações feitas por qualquer bot.

---

## 🚀 Como Executar

```bash
docker compose up --build
```
