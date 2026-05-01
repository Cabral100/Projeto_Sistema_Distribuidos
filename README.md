# Projeto Sistemas Distribuídos - Parte 4

## O que foi implementado

Esta parte modifica a sincronização do relógio físico dos servidores. Em vez de usar o serviço de referência como fonte de tempo, os próprios servidores elegem um **coordenador** entre si e ele passa a ser responsável por fornecer a hora correta aos demais. O serviço de referência continua existindo para rank, lista e heartbeat, mas **não retorna mais o timestamp no heartbeat**.

---

## Eleição — Algoritmo Bully

Cada servidor mantém uma variável com o nome do coordenador atual. Quando um servidor inicia ou detecta que o coordenador não está mais respondendo, ele dispara uma eleição seguindo o algoritmo Bully:

1. Consulta o serviço de referência com `funcao = "list"` para obter a lista de servidores ativos e seus ranks
2. Envia `ReqS2S(funcao="eleicao")` para todos os servidores com rank maior
3. Se algum responder `ok = True`, aguarda o anúncio do novo coordenador via pub/sub
4. Se **nenhum** responder, declara-se coordenador e publica seu próprio nome no tópico `servers`

Todos os servidores escutam o tópico `servers` via sub/pub e atualizam sua variável de coordenador ao receber o anúncio.

```
Servidor A  ──── REQ: eleicao ───────► Servidor B
            ◄─── REP: ok ────────────

Servidor B  ──── PUB: [servers] nome_coordenador ────► todos
```

---

## Sincronização do Relógio — Algoritmo de Berkeley

A cada **15 mensagens** processadas, cada servidor envia o heartbeat à referência e em seguida sincroniza o relógio com o coordenador:

- **Subordinado** — envia `ReqS2S(funcao="sync")` ao coordenador, recebe `ResS2S(timestamp=hora_do_coordenador)` e calcula o offset:

```
offset = hora_coordenador - hora_local
```

- **Coordenador** — não sincroniza, pois ele é a fonte de tempo
- Se o coordenador **não responder** ao sync, o servidor inicia uma nova eleição automaticamente

```
Servidor  ──── REQ: sync ────────────► Coordenador
          ◄─── REP: hora correta ─────
```

---

## Comunicação entre servidores (S2S)

Cada servidor abre um socket `REP` na porta `5560` exclusivamente para atender requisições de outros servidores. As mensagens utilizam dois novos tipos Protobuf adicionados ao `mensagens.proto`:

- `ReqS2S` — campos: `funcao` ("eleicao" ou "sync") e `relogio_logico`
- `ResS2S` — campos: `ok` (bool), `timestamp` (hora do coordenador, preenchido apenas no sync) e `relogio_logico`

---

## Arquivos alterados

| Arquivo | Alteração |
|---|---|
| `mensagens.proto` | Adicionadas as mensagens `ReqS2S` e `ResS2S` para comunicação direta entre servidores |
| `referencia.py` | Heartbeat não preenche mais `res.timestamp` na resposta |
| `servidor.py` | Variável de coordenador, eleição Bully, sync Berkeley, socket REP S2S na porta 5560, thread de eleição, thread de escuta do tópico `servers` |
| `docker-compose.yml` | Porta `5560` exposta nos servidores; variável `PUBSUB_SUB_URL` adicionada |
| `broker.py` | Sem alterações |
| `proxy_pubsub.py` | Sem alterações |
| `cliente.java` | Sem alterações |

---

## Troca de mensagens — visão geral

```
Servidor  ──── REQ: heartbeat ───────► Referência
          ◄─── REP: ok ──────────────  (sem timestamp — hora vem do coordenador)

Servidor  ──── REQ: eleicao ─────────► Servidores com rank maior
          ◄─── REP: ok ──────────────

Servidor  ──── PUB: [servers] nome ──► todos os servidores (via proxy pub/sub)

Servidor  ──── REQ: sync ────────────► Coordenador
          ◄─── REP: hora correta ─────
```

---

## Como Executar

```bash
docker compose up --build
```
