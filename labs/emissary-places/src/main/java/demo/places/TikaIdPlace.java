package demo.places;

import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

import org.apache.tika.detect.DefaultDetector;
import org.apache.tika.detect.Detector;
import org.apache.tika.io.TikaInputStream;
import org.apache.tika.metadata.Metadata;
import org.apache.tika.metadata.TikaCoreProperties;
import org.apache.tika.mime.MediaType;
import org.apache.tika.parser.ParseContext;

import emissary.core.Form;
import emissary.core.IBaseDataObject;
import emissary.place.ServiceProviderPlace;

/**
 * ID-stage place that identifies payloads Emissary's magic-number place left as UNKNOWN, using Tika's
 * detector (magic bytes, container inspection and the filename). Detection only: nothing is parsed, so
 * it runs in-process. Parsing happens in {@link TikaTextPlace}, in a forked JVM.
 */
public class TikaIdPlace extends ServiceProviderPlace {

    /** Parameter holding the original file name of an extracted child (set by UnzipPlace). */
    public static final String ORIGINAL_FILENAME = "ORIGINAL_FILENAME";
    public static final String MIME_TYPE = "MIME_TYPE";

    private final Detector detector = new DefaultDetector();
    private final Map<String, String> mimeToForm = new HashMap<>();

    /** Constructor used by Emissary's PlaceStarter. */
    public TikaIdPlace(String configInfo, String dir, String placeLoc) throws IOException {
        super(configInfo, dir, placeLoc);
        configure();
    }

    /** Constructor for tests. */
    public TikaIdPlace(InputStream configInfo, String placeLoc) throws IOException {
        super(configInfo, placeLoc);
        configure();
    }

    private void configure() {
        // MIME_FORM = "<mime type>:<form>" entries; anything else gets a form derived from the subtype.
        for (String entry : configG.findEntries("MIME_FORM")) {
            int i = entry.lastIndexOf(':');
            if (i > 0) {
                mimeToForm.put(entry.substring(0, i).trim().toLowerCase(Locale.ROOT), entry.substring(i + 1).trim());
            }
        }
    }

    @Override
    public void process(IBaseDataObject d) {
        MediaType type = detect(d);
        if (type == null || MediaType.OCTET_STREAM.equals(type)) {
            return; // still unknown; leave the form alone
        }
        String form = formFor(type);
        d.replaceCurrentForm(form);
        d.setFileType(form);
        d.putParameter(MIME_TYPE, type.toString());
    }

    MediaType detect(IBaseDataObject d) {
        Metadata md = new Metadata();
        String name = nameHint(d);
        if (name != null) {
            md.set(TikaCoreProperties.RESOURCE_NAME_KEY, name);
        }
        try (TikaInputStream tis = TikaInputStream.get(d.data())) {
            return detector.detect(tis, md, new ParseContext()).getBaseType();
        } catch (IOException | RuntimeException e) {
            d.addProcessingError("TikaIdPlace: detection failed: " + e);
            logger.warn("Tika detection failed for {}", d.shortName(), e);
            return null;
        }
    }

    /** Extracted children are named like x.zip-att-1, so prefer the entry's own file name. */
    private static String nameHint(IBaseDataObject d) {
        String original = d.getStringParameter(ORIGINAL_FILENAME);
        if (original != null && !original.isEmpty()) {
            return original;
        }
        String filename = d.getFilename();
        if (filename == null) {
            return null;
        }
        int slash = Math.max(filename.lastIndexOf('/'), filename.lastIndexOf('\\'));
        return filename.substring(slash + 1);
    }

    String formFor(MediaType type) {
        String mapped = mimeToForm.get(type.toString().toLowerCase(Locale.ROOT));
        if (mapped != null) {
            return mapped;
        }
        String sub = type.getSubtype().replaceFirst("^(x-|vnd\\.)", "").toUpperCase(Locale.ROOT).replaceAll("[^A-Z0-9]+", "_");
        if ("image".equals(type.getType())) {
            return "IMAGE_" + sub;
        }
        return sub.isEmpty() ? Form.UNKNOWN : sub;
    }
}
