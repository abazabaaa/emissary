package demo.places;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

import org.apache.tika.exception.TikaConfigException;
import org.apache.tika.io.TikaInputStream;
import org.apache.tika.language.detect.LanguageDetector;
import org.apache.tika.language.detect.LanguageResult;
import org.apache.tika.metadata.DublinCore;
import org.apache.tika.metadata.HttpHeaders;
import org.apache.tika.metadata.Metadata;
import org.apache.tika.metadata.PagedText;
import org.apache.tika.metadata.Property;
import org.apache.tika.metadata.TikaCoreProperties;
import org.apache.tika.pipes.fork.PipesForkParser;
import org.apache.tika.pipes.fork.PipesForkResult;

import demo.places.support.TikaForks;
import emissary.core.IBaseDataObject;
import emissary.place.ServiceProviderPlace;

/**
 * ANALYZE-stage place that extracts text and document metadata with Apache Tika 4. Parsing runs in
 * forked JVMs ({@link TikaForks}); only language detection on the extracted text runs in-process.
 * The payload bytes are not modified: text goes to the {@code TEXT} alternate view (Markdown) and
 * metadata to parameters.
 */
public class TikaTextPlace extends ServiceProviderPlace {

    public static final String TEXT_VIEW = "TEXT";
    public static final String TEXT_CHARS = "TEXT_CHARS";
    public static final String PAGE_COUNT = "PAGE_COUNT";

    private final Set<String> excludePrefixes = new HashSet<>();
    private PipesForkParser forks;
    private LanguageDetector languageDetector;

    public TikaTextPlace(String configInfo, String dir, String placeLoc) throws IOException {
        super(configInfo, dir, placeLoc);
        configure();
    }

    public TikaTextPlace(InputStream configInfo, String placeLoc) throws IOException {
        super(configInfo, placeLoc);
        configure();
    }

    private void configure() throws IOException {
        for (String f : configG.findEntries("EXCLUDE_FORM_PREFIX")) {
            excludePrefixes.add(f.toUpperCase(Locale.ROOT));
        }
        TikaForks.Settings s = new TikaForks.Settings(
                configG.findIntEntry("NUM_FORKS", 2),
                configG.findStringEntry("FORK_HEAP", "512m"),
                configG.findLongEntry("TASK_TIMEOUT_MILLIS", 120_000L),
                configG.findLongEntry("PROGRESS_TIMEOUT_MILLIS", 60_000L),
                System.getProperty("demo.tika.javaPath", configG.findStringEntry("FORK_JAVA_PATH", "")),
                configG.findIntEntry("MAX_TEXT_CHARS", 10_000_000));
        try {
            forks = TikaForks.acquire(s);
        } catch (TikaConfigException e) {
            throw new IOException("Cannot start Tika fork pool", e);
        }
        languageDetector = LanguageDetector.getDefaultLanguageDetector();
        languageDetector.loadModels();
    }

    @Override
    public void shutDown() {
        super.shutDown();
        if (forks != null) {
            forks = null;
            TikaForks.release();
        }
    }

    @Override
    public void process(IBaseDataObject d) {
        String form = d.currentForm();
        if (form == null || excludePrefixes.stream().anyMatch(p -> form.toUpperCase(Locale.ROOT).startsWith(p))) {
            return;
        }
        Metadata md = new Metadata();
        String name = d.getStringParameter(TikaIdPlace.ORIGINAL_FILENAME);
        if (name != null) {
            md.set(TikaCoreProperties.RESOURCE_NAME_KEY, name);
        }
        PipesForkResult result;
        try (TikaInputStream tis = TikaInputStream.get(d.data())) {
            result = forks.parse(tis, md);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            d.addProcessingError("TikaTextPlace: interrupted");
            return;
        } catch (Exception e) {
            d.addProcessingError("TikaTextPlace: " + e);
            logger.warn("Tika parse failed for {}", d.shortName(), e);
            return;
        }
        if (!result.isSuccess()) {
            // Crash, OOM or timeout in the fork: record it and let the payload continue to output.
            d.addProcessingError("TikaTextPlace: " + result.getStatus() + (result.getMessage() == null ? "" : ": " + result.getMessage()));
            d.putParameter("TIKA_STATUS", String.valueOf(result.getStatus()));
            return;
        }
        Metadata out = result.getMetadata();
        String text = result.getContent() == null ? "" : result.getContent().strip();
        d.putParameter("TIKA_STATUS", "OK");
        d.putParameter(TEXT_CHARS, text.length());
        if (!text.isEmpty()) {
            d.addAlternateView(TEXT_VIEW, text.getBytes(StandardCharsets.UTF_8));
            LanguageResult lang = languageDetector.detect(text);
            if (!lang.isUnknown()) {
                d.putParameter("LANGUAGE", lang.getLanguage());
                d.putParameter("LANGUAGE_CONFIDENCE", String.format(Locale.ROOT, "%.2f", lang.getConfidenceScore()));
            }
        }
        copy(out, DublinCore.TITLE, d, "TITLE");
        copy(out, DublinCore.CREATOR, d, "AUTHOR");
        copy(out, DublinCore.CREATED, d, "CREATED");
        copy(out, DublinCore.MODIFIED, d, "MODIFIED");
        copy(out, PagedText.N_PAGES, d, PAGE_COUNT);
        String contentType = out.get(HttpHeaders.CONTENT_TYPE);
        if (contentType != null) {
            d.putParameter("CONTENT_TYPE", contentType);
        }
        String containerException = out.get(TikaCoreProperties.CONTAINER_EXCEPTION);
        if (containerException != null) {
            d.addProcessingError("TikaTextPlace: " + containerException.lines().findFirst().orElse(""));
        }
    }

    private static void copy(Metadata from, Property key, IBaseDataObject to, String param) {
        String v = from.get(key);
        if (v != null && !v.isBlank()) {
            to.putParameter(param, v);
        }
    }
}
