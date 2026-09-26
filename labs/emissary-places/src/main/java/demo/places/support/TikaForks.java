package demo.places.support;

import java.io.IOException;
import java.util.List;

import org.apache.tika.config.TimeoutLimits;
import org.apache.tika.exception.TikaConfigException;
import org.apache.tika.pipes.fork.PipesForkParser;
import org.apache.tika.pipes.fork.PipesForkParserConfig;
import org.apache.tika.sax.BasicContentHandlerFactory;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * One {@link PipesForkParser} per Emissary node. It is thread-safe and spreads parses over a pool of
 * forked JVMs, so a parser crash, OOM or hang on a bad document kills a fork, not the node.
 */
public final class TikaForks {

    private static final Logger LOG = LoggerFactory.getLogger(TikaForks.class);

    /** Settings; the first place to call {@link #get} fixes them for the node. */
    public record Settings(int numForks, String heap, long taskTimeoutMillis, long progressTimeoutMillis,
            String javaPath, int writeLimitChars) {}

    private static PipesForkParser parser;
    private static int users;

    private TikaForks() {}

    public static synchronized PipesForkParser acquire(Settings s) throws IOException, TikaConfigException {
        if (parser == null) {
            PipesForkParserConfig cfg = new PipesForkParserConfig()
                    .setHandlerType(BasicContentHandlerFactory.HANDLER_TYPE.MARKDOWN)
                    .setWriteLimit(s.writeLimitChars())
                    // Emissary unpacks containers itself, so Tika should not recurse into them.
                    .setMaxEmbeddedCount(0)
                    .setNumClients(s.numForks())
                    .setJvmArgs(List.of("-Xmx" + s.heap()))
                    .setTimeoutLimits(new TimeoutLimits(s.taskTimeoutMillis(), s.progressTimeoutMillis()));
            if (s.javaPath() != null && !s.javaPath().isBlank()) {
                cfg.setJavaPath(s.javaPath());
            }
            parser = new PipesForkParser(cfg);
            LOG.info("Started Tika fork pool: {} forks, -Xmx{}, java={}", s.numForks(), s.heap(),
                    s.javaPath() == null || s.javaPath().isBlank() ? "java" : s.javaPath());
        }
        users++;
        return parser;
    }

    public static synchronized void release() {
        if (--users <= 0 && parser != null) {
            try {
                parser.close();
            } catch (IOException e) {
                LOG.warn("Error closing Tika fork pool", e);
            }
            parser = null;
            users = 0;
        }
    }
}
