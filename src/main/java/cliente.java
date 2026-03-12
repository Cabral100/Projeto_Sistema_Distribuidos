import org.zeromq.ZMQ;
import org.zeromq.ZContext;
import org.msgpack.core.*;
import org.msgpack.value.Value;

import java.io.IOException;
import java.util.*;

public class cliente {

    static final String BROKER   = System.getenv().getOrDefault("BROKER_URL", "tcp://broker:5555");
    static final String BOT_NAME = System.getenv().getOrDefault("BOT_NAME", "lucas"); // padrão válido

    static final Set<String> ALLOWED_USERS = Set.of("lucas", "joao", "maria", "carol", "artur");

    public static void main(String[] args) throws Exception {

        if (!ALLOWED_USERS.contains(BOT_NAME.toLowerCase())) {
            System.err.println("[ERRO] BOT_NAME='" + BOT_NAME + "' nao permitido. Validos: " + ALLOWED_USERS);
            System.exit(1);
        }

        // Aguarda broker e servidores estarem prontos
        System.out.println("[" + BOT_NAME + "] Aguardando 5s para infraestrutura subir...");
        Thread.sleep(5000);

        try (ZContext ctx = new ZContext()) {
            ZMQ.Socket socket = ctx.createSocket(ZMQ.REQ);
            socket.setReceiveTimeOut(5000);
            socket.connect(BROKER);
            System.out.println("[" + BOT_NAME + "] Conectado ao broker " + BROKER);

            // 1. Login com retry
            boolean loggedIn = false;
            while (!loggedIn) {
                socket.send(pack("login", Map.of("username", BOT_NAME.toLowerCase())));
                byte[] raw = socket.recv();

                if (raw == null) {
                    System.out.println("[LOGIN] Sem resposta, tentando novamente em 2s...");
                    Thread.sleep(2000);
                    continue;
                }

                Map<String, Object> resp = unpack(raw);
                System.out.println("[LOGIN] " + resp.get("status") + " - " + resp.get("mensagem"));
                loggedIn = "ok".equals(resp.get("status"));
                if (!loggedIn) Thread.sleep(2000);
            }

            // 2. Listar canais existentes
            listarCanais(socket);

            // 3. Criar canais
            criarCanal(socket, "geral");
            criarCanal(socket, "tech");
            criarCanal(socket, "geral"); // teste duplicata

            // 4. Listar após criação
            listarCanais(socket);
        }
    }

    static void listarCanais(ZMQ.Socket socket) throws IOException {
        socket.send(pack("listar_canais", Map.of()));
        Map<String, Object> resp = unpack(socket.recv());
        System.out.println("[LISTAR] canais=" + resp.get("canais"));
    }

    static void criarCanal(ZMQ.Socket socket, String canal) throws IOException {
        Map<String, Object> dados = Map.of("canal", canal, "username", BOT_NAME.toLowerCase());
        socket.send(pack("criar_canal", dados));
        Map<String, Object> resp = unpack(socket.recv());
        System.out.println("[CRIAR] " + resp.get("status") + " - " + resp.get("mensagem"));
    }

    static byte[] pack(String funcao, Map<String, Object> dados) throws IOException {
        MessageBufferPacker p = MessagePack.newDefaultBufferPacker();
        p.packMapHeader(3);
        p.packString("funcao");    p.packString(funcao);
        p.packString("timestamp"); p.packDouble(System.currentTimeMillis() / 1000.0);
        p.packString("dados");
        p.packMapHeader(dados.size());
        for (var e : dados.entrySet()) {
            p.packString(e.getKey());
            p.packString(e.getValue().toString());
        }
        p.close();
        return p.toByteArray();
    }

    static Map<String, Object> unpack(byte[] data) throws IOException {
        Map<String, Object> map = new LinkedHashMap<>();
        MessageUnpacker u = MessagePack.newDefaultUnpacker(data);
        int size = u.unpackMapHeader();
        for (int i = 0; i < size; i++) {
            String key = u.unpackString();
            Value  val = u.unpackValue();
            if (val.isArrayValue()) {
                List<String> list = new ArrayList<>();
                for (Value v : val.asArrayValue()) list.add(v.toString().replace("\"", ""));
                map.put(key, list);
            } else {
                map.put(key, val.toString().replace("\"", ""));
            }
        }
        u.close();
        return map;
    }
}