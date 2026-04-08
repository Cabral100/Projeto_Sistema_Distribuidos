# Projeto Sistemas Distribuídos - Parte 2

## 📌 Introdução
Esta parte adiciona publicação em canais via padrão **Publisher-Subscriber** ao sistema já existente de Req-Rep com broker. Os bots agora podem publicar mensagens em canais e receber mensagens de canais nos quais estão inscritos.

## 🛠️ Escolhas Técnicas

### 1. Arquitetura Pub/Sub separada do Req-Rep
Conforme especificado, o proxy Pub/Sub é um container separado do broker Req-Rep, utilizando:
- Porta **5557** como **XSUB** (recebe publicações dos servidores)
- Porta **5558** como **XPUB** (distribui mensagens para os clientes inscritos)

O servidor ao receber uma requisição `publicar_canal` via Req-Rep, publica a mensagem no proxy Pub/Sub conectando-se como `PUB` na porta 5557. O cliente Java mantém uma thread dedicada conectada como `SUB` na porta 5558, inscrita nos tópicos escolhidos.
### 2. Serialização (Protocol Buffers)
Para cumprir o requisito de comunicação binária:
* Utilizei **Google Protobuf** para definir um contrato rígido (`mensagens.proto`).
* Todas as mensagens incluem obrigatoriamente um campo `timestamp` (double) para rastreabilidade, conforme exigido.

### 2. Tópicos = Nomes dos Canais
O nome do canal é usado diretamente como prefixo do tópico ZMQ (`canal.encode()`). Isso permite que os subscribers filtrem mensagens apenas dos canais de interesse com `sub.subscribe(canal.getBytes())`.

### 3. Inscrição no cliente
A inscrição em canais é feita exclusivamente no cliente (conforme requisito): a thread `AssinanteThread` gerencia uma lista de canais inscritos e aplica novos `subscribe()` no socket SUB. Um único socket SUB pode se inscrever em múltiplos tópicos na mesma conexão com o proxy.

### 4. Serialização das publicações (Protobuf)
Foi adicionada a mensagem `Publicacao` ao `.proto` com os campos:
- `canal`, `username`, `mensagem`
- `timestamp_envio` (do cliente) e `timestamp_recebimento` (do servidor)

Todas as mensagens trocadas tanto para solicitar a publicação quanto para publicar no canal contêm timestamp de envio, conforme exigido.

### 5. Persistência em disco
O servidor persiste em `/data/{SERVER_NAME}_db.json`:
- **logins**: histórico de autenticações (usuário + timestamp)
- **canais**: lista de canais criados
- **publicacoes**: todas as mensagens publicadas, com canal, usuário, mensagem, timestamp de envio e de recebimento

Isso permite recuperar o histórico completo de publicações futuramente.

### 6. Funcionamento dos bots
Ao conectar, cada bot:
1. Faz login no servidor
2. Se existirem menos de 5 canais, cria um novo
3. Se estiver inscrito em menos de 3 canais, inscreve em mais um (aleatório)
4. Entra em loop infinito: escolhe um canal aleatório da lista e envia 10 mensagens com intervalo de 1 segundo entre elas
5. Mensagens recebidas via Pub/Sub são exibidas com: canal, remetente, conteúdo, timestamp de envio e timestamp de recebimento

## 🚀 Como Executar
```bash
docker compose up --build
```

## 📁 Arquivos entregues (novos/modificados na Parte 2)
- `proxy_pubsub.py` — proxy XSUB/XPUB para o padrão Pub/Sub
- `servidor.py` — atualizado com suporte a `publicar_canal` e persistência de publicações
- `src/main/java/cliente.java` — atualizado com thread assinante, inscrição em canais e envio de publicações
- `mensagens.proto` — adicionados campos `mensagem` no `Envelope` e nova mensagem `Publicacao`
- `docker-compose.yml` — adicionado serviço `proxy_pubsub` com portas 5557/5558
- `README.md` — atualizado com explicações da Parte 2
1. Certifique-se de ter os arquivos `mensagens.proto`, `cliente.java`, `servidor.py` e `broker.py` na estrutura correta.
2. Execute o comando:
   ```bash
   docker compose up --build
