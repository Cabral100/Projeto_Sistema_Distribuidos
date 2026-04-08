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
import java.util.concurrent.atomic.AtomicReference;

public class cliente {
    private static final DateTimeFormatter dtf = DateTimeFormatter.ofPattern("HH:mm:ss");
    private static final Random rng = new Random();

    private static void log(String user, String msg) {
        System.out.println("[" + dtf.format(LocalTime.now()) + "] [" + user + "] " + msg);
    }

    static class AssinanteThread extends Thread {
        private final ZContext ctx;
        private final String pubsubUrl;
        private final String user;
        private final List<String> canaisInscritos = new ArrayList<>();

        AssinanteThread(ZContext ctx, String pubsubUrl, String user) {
            this.ctx = ctx;
            this.pubsubUrl = pubsubUrl;
            this.user = user;
            this.setDaemon(true);
        }

        public synchronized void inscrever(String canal) {
            if (!canaisInscritos.contains(canal)) {
                canaisInscritos.add(canal);
                log(user, "Inscrito no canal: " + canal);
            }
        }

        public synchronized List<String> getCanaisInscritos() {
            return new ArrayList<>(canaisInscritos);
        }

        public synchronized int qtdInscritos() {
            return canaisInscritos.size();
        }

        @Override
        public void run() {
            ZMQ.Socket sub = ctx.createSocket(ZMQ.SUB);
            sub.connect(pubsubUrl);

            List<String> inscritosConhecidos = new ArrayList<>();

            while (!Thread.currentThread().isInterrupted()) {
                // Verifica novos canais para inscrever
                synchronized (this) {
                    for (String canal : canaisInscritos) {
                        if (!inscritosConhecidos.contains(canal)) {
                            sub.subscribe(canal.getBytes());
                            inscritosConhecidos.add(canal);
                        }
                    }
                }

                byte[] topico = sub.recv(ZMQ.DONTWAIT);
                if (topico != null && sub.hasReceiveMore()) {
                    byte[] payload = sub.recv();
                    try {
                        Publicacao pub = Publicacao.parseFrom(payload);
                        double tsRecebimento = System.currentTimeMillis() / 1000.0;

                        LocalTime tEnvio = LocalTime.ofInstant(
                            Instant.ofEpochMilli((long)(pub.getTimestampEnvio() * 1000)),
                            ZoneId.systemDefault()
                        );
                        LocalTime tRecebimento = LocalTime.ofInstant(
                            Instant.ofEpochMilli((long)(tsRecebimento * 1000)),
                            ZoneId.systemDefault()
                        );

                        System.out.println(
                            "[" + dtf.format(LocalTime.now()) + "] [" + user + "] " +
                            "[CANAL: " + pub.getCanal() + "] " +
                            "[DE: " + pub.getUsername() + "] " +
                            "[MSG: " + pub.getMensagem() + "] " +
                            "[ENVIADO: " + dtf.format(tEnvio) + "] " +
                            "[RECEBIDO: " + dtf.format(tRecebimento) + "]"
                        );
                    } catch (Exception e) {
                        log(user, "Erro ao deserializar publicacao: " + e.getMessage());
                    }
                } else {
                    try { Thread.sleep(50); } catch (InterruptedException ie) { break; }
                }
            }
            sub.close();
        }
    }

    public static void main(String[] args) throws Exception {
        String brokerUrl  = System.getenv().getOrDefault("BROKER_URL",  "tcp://broker:5555");
        String pubsubUrl  = System.getenv().getOrDefault("PUBSUB_URL",  "tcp://proxy_pubsub:5558");
        String user       = System.getenv().getOrDefault("BOT_NAME",    "bot");

        Thread.sleep(3000);

        try (ZContext ctx = new ZContext()) {
            ZMQ.Socket socket = ctx.createSocket(ZMQ.REQ);
            socket.connect(brokerUrl);
            socket.setReceiveTimeOut(5000);
            log(user, "Conectado ao broker: " + brokerUrl);

            AssinanteThread assinante = new AssinanteThread(ctx, pubsubUrl, user);
            assinante.start();

            boolean logado = false;
            while (!logado) {
                Envelope req = Envelope.newBuilder()
                    .setFuncao("login")
                    .setUsername(user)
                    .setTimestamp(System.currentTimeMillis() / 1000.0)
                    .build();
                socket.send(req.toByteArray());
                byte[] reply = socket.recv();
                if (reply != null) {
                    Resposta res = Resposta.parseFrom(reply);
                    log(user, "Login: " + res.getStatus() + " (" + res.getMensagem() + ")");
                    if (res.getStatus().equals("ok")) logado = true;
                }
                if (!logado) Thread.sleep(2000);
            }

            while (true) {
                socket.send(Envelope.newBuilder()
                    .setFuncao("listar_canais")
                    .setUsername(user)
                    .setTimestamp(System.currentTimeMillis() / 1000.0)
                    .build().toByteArray());
                byte[] reply = socket.recv();
                if (reply == null) continue;

                List<String> canais = new ArrayList<>(Resposta.parseFrom(reply).getCanaisList());
                log(user, "Canais disponiveis: " + canais);

                if (canais.size() < 5) {
                    String novoCanal = "canal-" + user + "-" + rng.nextInt(1000);
                    socket.send(Envelope.newBuilder()
                        .setFuncao("criar_canal")
                        .setUsername(user)
                        .setParametro(novoCanal)
                        .setTimestamp(System.currentTimeMillis() / 1000.0)
                        .build().toByteArray());
                    Resposta resCanal = Resposta.parseFrom(socket.recv());
                    log(user, "Criar canal '" + novoCanal + "': " + resCanal.getStatus());
                    // Atualiza lista
                    socket.send(Envelope.newBuilder()
                        .setFuncao("listar_canais")
                        .setUsername(user)
                        .setTimestamp(System.currentTimeMillis() / 1000.0)
                        .build().toByteArray());
                    reply = socket.recv();
                    if (reply != null) canais = new ArrayList<>(Resposta.parseFrom(reply).getCanaisList());
                }

                if (assinante.qtdInscritos() < 3 && !canais.isEmpty()) {
                    String canal = canais.get(rng.nextInt(canais.size()));
                    assinante.inscrever(canal);
                }

                for (int i = 0; i < 10; i++) {
                    if (canais.isEmpty()) break;
                    String canalEscolhido = canais.get(rng.nextInt(canais.size()));
                    String texto = "msg-" + rng.nextInt(10000) + " de " + user;

                    socket.send(Envelope.newBuilder()
                        .setFuncao("publicar_canal")
                        .setUsername(user)
                        .setParametro(canalEscolhido)
                        .setMensagem(texto)
                        .setTimestamp(System.currentTimeMillis() / 1000.0)
                        .build().toByteArray());

                    byte[] pubReply = socket.recv();
                    if (pubReply != null) {
                        Resposta res = Resposta.parseFrom(pubReply);
                        log(user, "Publicou em '" + canalEscolhido + "': " + res.getStatus());
                    }
                    Thread.sleep(1000);
                }
            }
        } catch (Exception e) {
            System.err.println("Erro: " + e.getMessage());
            e.printStackTrace();
        }
    }
}
