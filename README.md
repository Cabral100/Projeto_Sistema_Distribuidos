# Projeto Sistemas Distribuídos - Parte 3


### O que foi implementado

Esta parte adiciona **relógio lógico de Lamport** em todos os processos do sistema e um novo **serviço de referência** responsável por sincronizar o relógio físico dos servidores e manter a lista de servidores disponíveis via heartbeat.

---

### Relógio Lógico (Lamport)

O relógio lógico foi implementado tanto nos clientes Java quanto nos servidores Python, seguindo as duas regras do algoritmo de Lamport:

1. O contador é **incrementado antes do envio** de cada mensagem e enviado junto com ela (campo `relogio_logico` no Protobuf).
2. Ao **receber uma mensagem**, o processo atualiza seu contador para `max(local, recebido) + 1`.

O campo `relogio_logico` foi adicionado às mensagens `Envelope`, `Resposta` e `Publicacao` no arquivo `mensagens.proto`. Todos os logs passaram a exibir o valor atual do relógio lógico no formato `[RL=N]`.

---

### Serviço de Referência (`referencia.py`)

Um novo processo foi criado e adicionado ao `docker-compose.yml` como serviço `referencia`, exposto na porta `5559`. Ele utiliza socket `REP` e se comunica exclusivamente com os servidores (nunca com os clientes). Suas responsabilidades são:

**1. Informar o rank do servidor**

Quando um servidor inicia, ele envia uma requisição com `funcao = "rank"` e seu nome. O serviço de referência atribui um rank incremental único (sem repetição de nome) e retorna o valor:

```
REQ: { funcao: "rank", nome: "servidor1" }
REP: { status: "ok", rank: 1 }
```

**2. Armazenar a lista de servidores cadastrados**

A cada requisição de rank, o serviço registra internamente o nome e rank do servidor. Nomes já cadastrados não geram novo rank — apenas renovam o heartbeat.

**3. Fornecer a lista de servidores**

Qualquer servidor pode consultar a lista de todos os servidores disponíveis:

```
REQ: { funcao: "list" }
REP: { status: "ok", servidores: [{ nome: "servidor1", rank: 1 }, ...] }
```

**4. Heartbeat e remoção de servidores inativos**

A cada **10 mensagens de clientes recebidas**, o servidor envia um heartbeat ao serviço de referência:

```
REQ: { funcao: "heartbeat", nome: "servidor1" }
REP: { status: "ok", timestamp: <hora_atual> }
```

Uma thread de monitor roda em background no serviço de referência verificando a cada 10 segundos se algum servidor ultrapassou o timeout de heartbeat (60 segundos). Servidores sem resposta são removidos da lista de disponíveis.

**5. Sincronização do relógio físico**

Aproveitando a mensagem de heartbeat, o servidor sincroniza seu relógio físico com o da referência. O timestamp retornado na resposta do heartbeat representa a hora atual da referência. O servidor estima a hora correta compensando metade do RTT (Round-Trip Time):

```
offset = (t_referencia + RTT/2) - t_local
```

Todas as operações subsequentes do servidor usam `time.time() + offset` como hora sincronizada.

---

### Arquivos alterados

| Arquivo | Alteração |
|---|---|
| `referencia.py` | **Novo** — serviço de referência completo |
| `servidor.py` | Relógio lógico, heartbeat periódico, sync do relógio físico, obtenção de rank na inicialização |
| `src/main/java/cliente.java` | Relógio lógico com `AtomicLong` thread-safe em todas as mensagens enviadas e recebidas |
| `mensagens.proto` | Campo `relogio_logico` em `Envelope`, `Resposta` e `Publicacao`; novas mensagens `ReqReferencia`, `ResReferencia` e `ServidorInfo` |
| `docker-compose.yml` | Adicionado serviço `referencia` (porta 5559, healthcheck); servidores passam a depender de `referencia: service_healthy` e recebem a variável `REFERENCIA_URL` |
| `broker.py` | Sem alterações |
| `proxy_pubsub.py` | Sem alterações |

---

### Troca de mensagens — visão geral

```
Servidor  ──── REQ: rank ────────────► Referência
          ◄─── REP: rank ─────────────

Servidor  ──── REQ: list ────────────► Referência
          ◄─── REP: [nomes e ranks] ──

Servidor  ──── REQ: heartbeat ───────► Referência
          ◄─── REP: OK + timestamp ───  (usado para sync do relógio)
```

---

### Como Executar

```bash
docker compose up --build
```
