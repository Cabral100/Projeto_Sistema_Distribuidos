import org.zeromq.ZMQ;
import org.zeromq.ZContext;
import sistema.Mensagens.Envelope;
import sistema.Mensagens.Resposta;
import sistema.Mensagens.Publicacao;
import java.time.Instant;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.Random;
import java.util.concurrent.atomic.AtomicLong;

public class cliente {
    private static final DateTimeFormatter dtf = DateTimeFormatter.ofPattern("HH:mm:ss");
    private static final Random rng = new Random();
    private static final AtomicLong relogioLogico = new AtomicLong(0);

    private static long rlEnviar() {
        return relogioLogico.incrementAndGet();
    }

    private static long rlReceber(long recebido) {
        long atual, novo;
        do {
            atual = relogioLogico.get();
            novo = Math.max(atual, recebido) + 1;
        } while (!relogioLogico.compareAndSet(atual, novo));
        return novo;
    }

    private static void log(String user, String msg) {
        System.out.println("[" + dtf.format(LocalTime.now()) + "] [" + user + "] [RL=" + relogioLogico.get() + "] " + msg);
    }

    // ── Thread assinante PubSub ───────────────────────────────────────────
    static class AssinanteThread extends Thread {
        private final ZContext ctx;
        private final String pubsubUrl;
        private final String user;
        private final List<String> canaisInscritos = new ArrayList<>();
        private volatile boolean running = true;

        AssinanteThread(ZContext ctx, String pubsubUrl, String user) {
            this.ctx = ctx;
            this.pubsubUrl = pubsubUrl;
            this.user = user;
            this.setDaemon(true);
        }

        public void encerrar() {
            running = false;
            this.interrupt();
        }

        public synchronized void inscrever(String canal) {
            if (!canaisInscritos.contains(canal)) {
                canaisInscritos.add(canal);
                log(user, "Inscrito no canal: " + canal);
            }
        }

        public synchronized int qtdInscritos() {
            return canaisInscritos.size();
        }

        @Override
        public void run() {
            ZMQ.Socket sub = ctx.createSocket(ZMQ.SUB);
            sub.connect(pubsubUrl);
            List<String> inscritosConhecidos = new ArrayList<>();

            while (running && !Thread.currentThread().isInterrupted()) {
                synchronized (this) {
                    for (String canal : canaisInscritos) {
                        if (!inscritosConhecidos.contains(canal)) {
                            sub.subscribe(canal.getBytes());
                            inscritosConhecidos.add(canal);
                        }
                    }
                }

                byte[] topico;
                try {
                    topico = sub.recv(ZMQ.DONTWAIT);
                } catch (Exception e) {
                    break;
                }

                if (topico != null && sub.hasReceiveMore()) {
                    byte[] payload;
                    try {
                        payload = sub.recv();
                    } catch (Exception e) {
                        break;
                    }
                    try {
                        Publicacao pub = Publicacao.parseFrom(payload);
                        double tsRecebimento = System.currentTimeMillis() / 1000.0;
                        long rlAtual = rlReceber(pub.getRelogioLogico());

                        LocalTime tEnvio = LocalTime.ofInstant(
                            Instant.ofEpochMilli((long)(pub.getTimestampEnvio() * 1000)),
                            ZoneId.systemDefault());
                        LocalTime tRecebimento = LocalTime.ofInstant(
                            Instant.ofEpochMilli((long)(tsRecebimento * 1000)),
                            ZoneId.systemDefault());

                        System.out.println(
                            "[" + dtf.format(LocalTime.now()) + "] [" + user + "] " +
                            "[RL=" + rlAtual + "] " +
                            "[CANAL: " + pub.getCanal() + "] " +
                            "[DE: " + pub.getUsername() + "] " +
                            "[MSG: " + pub.getMensagem() + "] " +
                            "[ENVIADO: " + dtf.format(tEnvio) + "] " +
                            "[RECEBIDO: " + dtf.format(tRecebimento) + "]");
                    } catch (Exception e) {
                        log(user, "Erro ao deserializar publicacao: " + e.getMessage());
                    }
                } else {
                    try { Thread.sleep(50); } catch (InterruptedException ie) { break; }
                }
            }
            try { sub.close(); } catch (Exception ignored) {}
        }
    }

    // ── Envia e recebe com retry automatico ao reconectar ────────────────
    private static byte[] enviarComRetry(ZContext ctx, ZMQ.Socket[] socketHolder,
                                          String brokerUrl, byte[] payload, String user) {
        int tentativas = 3;
        while (tentativas-- > 0) {
            try {
                socketHolder[0].send(payload);
                byte[] reply = socketHolder[0].recv();
                if (reply != null) return reply;
                log(user, "Timeout na resposta, reconectando ao broker...");
            } catch (Exception e) {
                log(user, "Erro no socket (" + e.getMessage() + "), reconectando...");
            }
            // Fecha socket com problema e cria um novo
            try { socketHolder[0].close(); } catch (Exception ignored) {}
            ZMQ.Socket novoSocket = ctx.createSocket(ZMQ.REQ);
            novoSocket.connect(brokerUrl);
            novoSocket.setReceiveTimeOut(5000);
            socketHolder[0] = novoSocket;
            try { Thread.sleep(2000); } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                return null;
            }
        }
        return null;
    }

    public static void main(String[] args) throws Exception {
        String brokerUrl = System.getenv().getOrDefault("BROKER_URL", "tcp://broker:5555");
        String pubsubUrl = System.getenv().getOrDefault("PUBSUB_URL", "tcp://proxy_pubsub:5558");
        String user      = System.getenv().getOrDefault("BOT_NAME",   "bot");

        Thread.sleep(3000);

        AssinanteThread assinante = null;
        try (ZContext ctx = new ZContext()) {
            ZMQ.Socket[] socketHolder = new ZMQ.Socket[1];
            socketHolder[0] = ctx.createSocket(ZMQ.REQ);
            socketHolder[0].connect(brokerUrl);
            socketHolder[0].setReceiveTimeOut(5000);
            log(user, "Conectado ao broker: " + brokerUrl);

            assinante = new AssinanteThread(ctx, pubsubUrl, user);
            assinante.start();

            // ── Login ────────────────────────────────────────────────────
            boolean logado = false;
            while (!logado) {
                byte[] reply = enviarComRetry(ctx, socketHolder, brokerUrl,
                    Envelope.newBuilder()
                        .setFuncao("login")
                        .setUsername(user)
                        .setTimestamp(System.currentTimeMillis() / 1000.0)
                        .setRelogioLogico(rlEnviar())
                        .build().toByteArray(), user);

                if (reply != null) {
                    Resposta res = Resposta.parseFrom(reply);
                    rlReceber(res.getRelogioLogico());
                    log(user, "Login: " + res.getStatus() + " (" + res.getMensagem() + ")");
                    if (res.getStatus().equals("ok")) logado = true;
                }
                if (!logado) Thread.sleep(2000);
            }

            // ── Loop principal ───────────────────────────────────────────
            while (true) {
                // Listar canais
                byte[] reply = enviarComRetry(ctx, socketHolder, brokerUrl,
                    Envelope.newBuilder()
                        .setFuncao("listar_canais")
                        .setUsername(user)
                        .setTimestamp(System.currentTimeMillis() / 1000.0)
                        .setRelogioLogico(rlEnviar())
                        .build().toByteArray(), user);
                if (reply == null) continue;

                Resposta resLista = Resposta.parseFrom(reply);
                rlReceber(resLista.getRelogioLogico());
                List<String> canais = new ArrayList<>(resLista.getCanaisList());
                log(user, "Canais disponiveis: " + canais);

                // Criar canal se necessario
                if (canais.size() < 5) {
                    String novoCanal = "canal-" + user + "-" + rng.nextInt(1000);
                    byte[] replyCanal = enviarComRetry(ctx, socketHolder, brokerUrl,
                        Envelope.newBuilder()
                            .setFuncao("criar_canal")
                            .setUsername(user)
                            .setParametro(novoCanal)
                            .setTimestamp(System.currentTimeMillis() / 1000.0)
                            .setRelogioLogico(rlEnviar())
                            .build().toByteArray(), user);
                    if (replyCanal != null) {
                        Resposta resCanal = Resposta.parseFrom(replyCanal);
                        rlReceber(resCanal.getRelogioLogico());
                        log(user, "Criar canal '" + novoCanal + "': " + resCanal.getStatus());
                    }
                    // Atualiza lista
                    byte[] replyLista2 = enviarComRetry(ctx, socketHolder, brokerUrl,
                        Envelope.newBuilder()
                            .setFuncao("listar_canais")
                            .setUsername(user)
                            .setTimestamp(System.currentTimeMillis() / 1000.0)
                            .setRelogioLogico(rlEnviar())
                            .build().toByteArray(), user);
                    if (replyLista2 != null) {
                        Resposta resCanalLista = Resposta.parseFrom(replyLista2);
                        rlReceber(resCanalLista.getRelogioLogico());
                        canais = new ArrayList<>(resCanalLista.getCanaisList());
                    }
                }

                // Inscrever em canal
                if (assinante.qtdInscritos() < 3 && !canais.isEmpty()) {
                    String canal = canais.get(rng.nextInt(canais.size()));
                    assinante.inscrever(canal);
                }

                // Publicar 10 mensagens
                for (int i = 0; i < 10; i++) {
                    if (canais.isEmpty()) break;
                    String canalEscolhido = canais.get(rng.nextInt(canais.size()));
                    String texto = "msg-" + rng.nextInt(10000) + " de " + user;

                    byte[] pubReply = enviarComRetry(ctx, socketHolder, brokerUrl,
                        Envelope.newBuilder()
                            .setFuncao("publicar_canal")
                            .setUsername(user)
                            .setParametro(canalEscolhido)
                            .setMensagem(texto)
                            .setTimestamp(System.currentTimeMillis() / 1000.0)
                            .setRelogioLogico(rlEnviar())
                            .build().toByteArray(), user);

                    if (pubReply != null) {
                        Resposta res = Resposta.parseFrom(pubReply);
                        rlReceber(res.getRelogioLogico());
                        log(user, "Publicou em '" + canalEscolhido + "': " + res.getStatus());
                    }
                    Thread.sleep(1000);
                }
            }
        } catch (Exception e) {
            System.err.println("Erro: " + e.getMessage());
            e.printStackTrace();
        } finally {
            if (assinante != null) assinante.encerrar();
        }
    }
}