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

---

## Replicação de Dados (Parte 5)

### Método escolhido: Replicação Ativa com Snapshot na Inicialização

O método escolhido foi a **Replicação Ativa** (*Active Replication*), também conhecida como abordagem *Primary-Backup* sem primário fixo: cada servidor que recebe e persiste uma publicação é responsável por propagá-la imediatamente a todos os demais servidores do cluster.

### Como o método resolve o problema

Com o broker em *round-robin*, cada mensagem chega inicialmente a apenas um servidor. Sem replicação, uma falha nesse servidor implica perda permanente dessas mensagens e histórico incompleto para os clientes. Com a Replicação Ativa:

1. **Toda publicação é propagada a todos os servidores ativos** logo após ser persistida localmente, via canal S2S (servidor a servidor) já existente no projeto.
2. **Servidores que reiniciam** solicitam um *snapshot* completo do banco de dados de qualquer par ativo antes de entrar em operação, garantindo que o histórico seja recuperado.
3. **Deduplicação** impede que uma mesma mensagem seja inserida duas vezes caso o servidor receba a replicação e também tente salvar localmente.

O resultado é que **todos os servidores mantêm todas as mensagens**, independentemente de qual deles atendeu originalmente o cliente.

### Implementação

A implementação foi feita inteiramente em `servidor.py` e `mensagens.proto`, sem alterações no broker, no cliente ou no serviço de referência.

#### Novos campos no `mensagens.proto` — mensagem `ReqS2S`

Foram adicionados campos opcionais a `ReqS2S` e `ResS2S` para transportar os dados de replicação sem criar novos tipos de mensagem:

```proto
message ReqS2S {
    string funcao = 1;
    int64  relogio_logico = 2;
    // Campos de replicação (funcao = "replicar")
    string canal                 = 3;
    string username              = 4;
    string mensagem              = 5;
    double timestamp_envio       = 6;
    double timestamp_recebimento = 7;
    // Campos de snapshot (funcao = "snapshot")
    string snapshot_json = 8;
}

message ResS2S {
    bool   ok              = 1;
    int64  timestamp       = 2;
    int64  relogio_logico  = 3;
    // Resposta de snapshot
    string snapshot_json   = 4;
}
```

#### Novos tipos de mensagem S2S em `servidor.py`

| `funcao`    | Direção                  | Descrição                                                                 |
|-------------|--------------------------|---------------------------------------------------------------------------|
| `replicar`  | servidor → outros        | Envia uma publicação para ser persistida nos pares                        |
| `snapshot`  | servidor → qualquer par  | Solicita o banco de dados completo (JSON) de um servidor ativo            |

#### Fluxo de replicação (publicação nova)

```
Cliente  →  Broker  →  Servidor A
                            │
                    persiste localmente
                            │
                    [thread em background]
                            ├──── replicar ──→  Servidor B  (persiste)
                            └──── replicar ──→  Servidor C  (persiste)
```

A replicação ocorre em uma *thread* daemon separada para não atrasar a resposta ao cliente. Servidores que não respondem dentro do timeout (2 s) são ignorados silenciosamente — eles se recuperam pelo mecanismo de snapshot ao reiniciar.

#### Fluxo de snapshot (servidor reiniciando)

```
Servidor D (reiniciando)
        │
        ├── lista servidores ativos via referência
        │
        └──── snapshot ──→  Servidor A
                                │
                          retorna DB completo (JSON)
                                │
                        Servidor D mescla e persiste
```

#### Deduplicação

A chave de deduplicação é a tupla `(canal, username, mensagem, timestamp_envio)`. Antes de inserir qualquer publicação recebida via `replicar` ou `snapshot`, o servidor verifica se essa chave já existe no banco local e descarta duplicatas.

### Adaptações necessárias

- **Thread safety:** o acesso ao banco de dados (`db`) passou a ser protegido por `threading.Lock` (`_db_lock`) em todas as operações de leitura e escrita, pois agora múltiplas threads (loop principal + `thread_s2s` + replicação em background) podem acessar o banco simultaneamente.
- **Canal S2S existente reutilizado:** os novos tipos de mensagem (`replicar` e `snapshot`) foram adicionados ao `thread_s2s` já existente, sem necessidade de novas portas ou sockets.
- **Nenhuma alteração no broker ou no cliente:** a transparência da replicação é total para os demais componentes.

## Como executar

```bash
docker compose up --build
```
