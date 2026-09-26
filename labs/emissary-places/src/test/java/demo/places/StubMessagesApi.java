package demo.places;

import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

import com.sun.net.httpserver.HttpServer;

/** A local stand-in for POST /v1/messages that replays scripted responses and records requests. */
final class StubMessagesApi implements AutoCloseable {

    record Reply(int status, String body, Map<String, String> headers) {}

    record Request(String body, Map<String, String> headers) {}

    private final HttpServer server;
    private final Deque<Reply> script = new ArrayDeque<>();
    final List<Request> requests = new ArrayList<>();

    StubMessagesApi() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/messages", ex -> {
            String body = new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            Map<String, String> hdrs = new ConcurrentHashMap<>();
            ex.getRequestHeaders().forEach((k, v) -> hdrs.put(k.toLowerCase(), String.join(",", v)));
            Reply r;
            synchronized (this) {
                requests.add(new Request(body, hdrs));
                r = script.isEmpty() ? text("end_turn", "(unscripted)") : script.poll();
            }
            byte[] out = r.body().getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("content-type", "application/json");
            r.headers().forEach((k, v) -> ex.getResponseHeaders().add(k, v));
            ex.sendResponseHeaders(r.status(), out.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(out);
            }
        });
        server.start();
    }

    String baseUrl() {
        return "http://127.0.0.1:" + server.getAddress().getPort();
    }

    synchronized StubMessagesApi then(Reply r) {
        script.add(r);
        return this;
    }

    static Reply text(String stopReason, String text) {
        return new Reply(200, message(stopReason, "[{\"type\":\"text\",\"text\":" + json(text) + "}]", ""), Map.of());
    }

    /** Opus 5 returns a (possibly empty) thinking block before the text; the place must skip it. */
    static Reply thinkingThenText(String text) {
        return new Reply(200, message("end_turn",
                "[{\"type\":\"thinking\",\"thinking\":\"\",\"signature\":\"sig\"},{\"type\":\"text\",\"text\":" + json(text) + "}]", ""),
                Map.of());
    }

    static Reply refusal(String category) {
        return new Reply(200, message("refusal", "[]",
                ",\"stop_details\":{\"type\":\"refusal\",\"category\":" + json(category) + ",\"explanation\":\"declined\"}"), Map.of());
    }

    static Reply rateLimited() {
        return new Reply(429, "{\"type\":\"error\",\"error\":{\"type\":\"rate_limit_error\",\"message\":\"slow down\"}}",
                Map.of("retry-after", "0"));
    }

    private static String message(String stopReason, String content, String extra) {
        return "{\"id\":\"msg_stub\",\"type\":\"message\",\"role\":\"assistant\",\"model\":\"claude-opus-5\","
                + "\"content\":" + content + ",\"stop_reason\":\"" + stopReason + "\",\"stop_sequence\":null" + extra
                + ",\"usage\":{\"input_tokens\":1000,\"output_tokens\":200}}";
    }

    private static String json(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n") + "\"";
    }

    @Override
    public void close() {
        server.stop(0);
    }
}
