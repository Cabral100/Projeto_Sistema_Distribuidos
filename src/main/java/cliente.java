import org.zeromq.ZMQ;
import org.zeromq.ZContext;
import sistema.Mensagens.Envelope;
import sistema.Mensagens.Resposta;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;

public class cliente {
    private static final DateTimeFormatter dtf = DateTimeFormatter.ofPattern("HH:mm:ss");

    private static void log(String user, String msg) {
        System.out.println("[" + dtf.format(LocalTime.now()) + "] [" + user + "] " + msg);
    }

    public static void main(String[] args) throws Exception {
        String broker = System.getenv().getOrDefault("BROKER_URL", "tcp://broker:5555");
        String user = System.getenv().getOrDefault("BOT_NAME", "bot");

        Thread.sleep(2000); 

        try (ZContext ctx = new ZContext()) {
            ZMQ.Socket socket = ctx.createSocket(ZMQ.REQ);
            socket.connect(broker);
            socket.setReceiveTimeOut(5000);
            log(user, "Conectado ao broker: " + broker);

            boolean logado = false;
            while (!logado) {
                Envelope req = Envelope.newBuilder()
                    .setFuncao("login")
                    .setUsername(user)
                    .setTimestamp(System.currentTimeMillis() / 1000.0).build();
                
                socket.send(req.toByteArray());
                byte[] reply = socket.recv();

                if (reply != null) {
                    Resposta res = Resposta.parseFrom(reply);
                    log(user, "Resposta Login: " + res.getStatus() + " (" + res.getMensagem() + ")");
                    if (res.getStatus().equals("ok")) logado = true;
                }
                if (!logado) Thread.sleep(2000);
            }

            String meuCanal = "canal-" + user;
            socket.send(Envelope.newBuilder()
                .setFuncao("criar_canal").setParametro(meuCanal)
                .setTimestamp(System.currentTimeMillis() / 1000.0).build().toByteArray());
            socket.recv(); 

            while (true) {
                socket.send(Envelope.newBuilder()
                    .setFuncao("listar_canais")
                    .setTimestamp(System.currentTimeMillis() / 1000.0).build().toByteArray());
                
                byte[] reply = socket.recv();
                if (reply != null) {
                    log(user, "Canais: " + Resposta.parseFrom(reply).getCanaisList());
                }
                Thread.sleep(5000);
            }
        } catch (Exception e) {
            System.err.println("Erro: " + e.getMessage());
        }
    }
}