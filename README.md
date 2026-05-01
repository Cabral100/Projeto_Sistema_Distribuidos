# Sistema de Troca de Mensagens Instantâneas

Projeto da disciplina de Sistemas Distribuídos do curso de Ciência da Computação

## Linguagens

- **Servidor:** Python
- **Cliente:** Java

Ambas foram escolhidas por conta da experiência prévia no desenvolvimento de projetos com elas.

## Serialização

A troca de mensagens utiliza Protobuf. Além da experiência prévia com a tecnologia, é o formato binário mais utilizado atualmente para comunicação entre serviços distribuídos.

## Persistência

SQLite para persistência das mensagens, por conta da simplicidade e por não exigir infraestrutura adicional.

## Troca de mensagens

A comunicação é dividida em dois padrões:

**Request-Reply** — clientes enviam requisições ao servidor através de um broker `ROUTER/DEALER`. O broker distribui as requisições entre os servidores disponíveis e devolve a resposta ao cliente correto. Usado para login, criação de canais, listagem de canais e publicação de mensagens.

**Pub/Sub** — um proxy `XPUB/XSUB` independente distribui as mensagens em tempo real. Ao publicar, o servidor encaminha a mensagem ao proxy usando o nome do canal como tópico. Os clientes inscritos naquele canal recebem a mensagem automaticamente.

As publicações são armazenadas no banco de dados contendo o username, o canal, a mensagem e o timestamp.

## Eleição e Sincronização de Relógio

Os servidores mantêm um relógio lógico de Lamport para ordenação causal dos eventos. Para o relógio físico, os servidores elegem um coordenador entre si usando o **algoritmo Bully** e sincronizam o tempo com o coordenador eleito usando o **algoritmo de Berkeley**, a cada 15 mensagens processadas.

Um serviço de referência separado é responsável por registrar os servidores, atribuir ranks e receber heartbeats para detectar servidores inativos.

## Como executar

```bash
docker compose up --build
```
