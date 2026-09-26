package demo.places;

import java.awt.Image;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

import javax.imageio.ImageIO;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.multipdf.PageExtractor;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.rendering.PDFRenderer;

import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import com.anthropic.errors.AnthropicException;
import com.anthropic.models.beta.AnthropicBeta;
import com.anthropic.models.beta.messages.BetaBase64ImageSource;
import com.anthropic.models.beta.messages.BetaBase64PdfSource;
import com.anthropic.models.beta.messages.BetaContentBlock;
import com.anthropic.models.beta.messages.BetaContentBlockParam;
import com.anthropic.models.beta.messages.BetaImageBlockParam;
import com.anthropic.models.beta.messages.BetaMessage;
import com.anthropic.models.beta.messages.BetaOutputConfig;
import com.anthropic.models.beta.messages.BetaRequestDocumentBlock;
import com.anthropic.models.beta.messages.BetaStopReason;
import com.anthropic.models.beta.messages.MessageCreateParams;

import emissary.core.IBaseDataObject;
import emissary.place.ServiceProviderPlace;

/**
 * ANALYZE-stage place that transcribes scanned images and image-only PDFs with Claude, using the
 * official Anthropic Java SDK. Runs after {@link TikaTextPlace} and only where Tika found little or
 * no text, so documents that already have text are never sent.
 * <p>
 * Every response's stop reason is checked: a response cut off at max_tokens is re-requested with
 * fewer pages, a refusal is recorded with its category, and nothing is silently dropped. Results
 * go to the {@code OCR_TEXT} view; status and token usage go to parameters for audit.
 * <p>
 * <b>Data leaves the node</b>: when enabled, page images are sent to Anthropic's API. Disabled
 * unless {@code OCR_ENABLED = "true"} and API credentials are present.
 */
public class ClaudeOcrPlace extends ServiceProviderPlace {

    public static final String OCR_VIEW = "OCR_TEXT";

    /** Per-batch outcome, rolled up into OCR_STATUS. */
    enum Outcome {
        COMPLETE, TRUNCATED, REFUSED, ERROR
    }

    record Batch(Outcome outcome, String text, int pages, String detail) {}

    private static final Set<String> IMAGE_FORMS_DIRECT = Set.of("IMAGE_PNG", "IMAGE_JPEG", "IMAGE_GIF", "IMAGE_WEBP");

    private boolean active;
    private AnthropicClient client;
    private String model;
    private long maxTokens;
    private BetaOutputConfig.Effort effort;
    private String prompt;
    private int pagesPerRequest;
    private long maxRequestBytes;
    private int maxLongEdge;
    private int minCharsPerPage;
    private int renderDpi;

    // Token and request totals for this document, kept per call so concurrent agents don't mix.
    private static final class Usage {
        long input;
        long output;
        int requests;
        final Set<String> models = new LinkedHashSet<>();
    }

    public ClaudeOcrPlace(String configInfo, String dir, String placeLoc) throws IOException {
        super(configInfo, dir, placeLoc);
        configure();
    }

    public ClaudeOcrPlace(InputStream configInfo, String placeLoc) throws IOException {
        super(configInfo, placeLoc);
        configure();
    }

    private void configure() {
        model = configG.findStringEntry("MODEL", "claude-opus-5");
        maxTokens = configG.findLongEntry("MAX_TOKENS", 16000L);
        effort = BetaOutputConfig.Effort.of(configG.findStringEntry("EFFORT", "medium").toLowerCase(Locale.ROOT));
        prompt = configG.findStringEntry("PROMPT", "Transcribe all text in this document exactly as written, in reading order. "
                + "Use Markdown for headings, lists and tables. Mark illegible words as [illegible]. "
                + "Do not summarize, translate, correct or describe the document; output only the transcription.");
        pagesPerRequest = configG.findIntEntry("PAGES_PER_REQUEST", 5);
        maxRequestBytes = configG.findLongEntry("MAX_REQUEST_BYTES", 20L * 1024 * 1024);
        maxLongEdge = configG.findIntEntry("MAX_LONG_EDGE_PX", 2576);
        minCharsPerPage = configG.findIntEntry("MIN_CHARS_PER_PAGE", 50);
        renderDpi = configG.findIntEntry("RENDER_DPI", 150);

        boolean enabled = configG.findBooleanEntry("OCR_ENABLED", false);
        if (!enabled) {
            logger.info("ClaudeOcrPlace disabled (OCR_ENABLED is false); images and scanned PDFs will get no OCR text");
            return;
        }
        String baseUrl = configG.findStringEntry("API_BASE_URL", "");
        String testKey = System.getProperty("demo.ocr.apiKey"); // tests only; production uses the SDK's credential chain
        if (testKey == null && !hasCredentials()) {
            logger.warn("ClaudeOcrPlace enabled but no Anthropic credentials found (set ANTHROPIC_API_KEY); OCR is off");
            return;
        }
        AnthropicOkHttpClient.Builder b = AnthropicOkHttpClient.builder().fromEnv()
                .maxRetries(configG.findIntEntry("MAX_RETRIES", 2))
                .timeout(Duration.ofSeconds(configG.findLongEntry("TIMEOUT_SECONDS", 600L)));
        if (testKey != null) {
            b.apiKey(testKey);
        }
        if (!baseUrl.isBlank()) {
            b.baseUrl(baseUrl);
        }
        client = b.build();
        active = true;
        logger.warn("ClaudeOcrPlace ENABLED: page images of scanned documents will be sent to {} (model {})",
                baseUrl.isBlank() ? "Anthropic's API" : baseUrl, model);
    }

    private static boolean hasCredentials() {
        for (String v : List.of("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE")) {
            String s = System.getenv(v);
            if (s != null && !s.isBlank()) {
                return true;
            }
        }
        return Files.isDirectory(Path.of(System.getProperty("user.home"), ".config", "anthropic"));
    }

    boolean isActive() {
        return active;
    }

    @Override
    public void shutDown() {
        super.shutDown();
        if (client != null) {
            client.close();
        }
    }

    @Override
    public void process(IBaseDataObject d) {
        if (!active) {
            return;
        }
        String form = d.currentForm();
        List<Batch> batches;
        Usage usage = new Usage();
        try {
            if ("PDF".equals(form)) {
                if (!needsOcr(d)) {
                    return;
                }
                batches = ocrPdf(d.data(), usage);
            } else if (imageForm(form) != null) {
                batches = List.of(ocrImage(d.data(), imageForm(form), usage));
            } else {
                return;
            }
        } catch (IOException e) {
            d.addProcessingError("ClaudeOcrPlace: cannot prepare input: " + e.getMessage());
            d.putParameter("OCR_STATUS", Outcome.ERROR.name());
            return;
        }
        record(d, batches, usage);
    }

    /**
     * Image forms come from two identifiers: TikaIdPlace says IMAGE_PNG, Emissary's UnixFilePlace
     * (magic numbers) says PNG. Normalise to the IMAGE_* names; null if not an image.
     */
    static String imageForm(String form) {
        if (form == null) {
            return null;
        }
        if (form.startsWith("IMAGE_")) {
            return form;
        }
        switch (form) {
            case "PNG":
            case "JPEG":
            case "GIF":
            case "TIFF":
            case "WEBP":
                return "IMAGE_" + form;
            default:
                return null;
        }
    }

    /** A PDF needs OCR when Tika found fewer than MIN_CHARS_PER_PAGE characters per page. */
    boolean needsOcr(IBaseDataObject d) {
        long chars = parseLong(d.getStringParameter(TikaTextPlace.TEXT_CHARS), 0);
        long pages = Math.max(1, parseLong(d.getStringParameter(TikaTextPlace.PAGE_COUNT), 1));
        return chars / pages < minCharsPerPage;
    }

    // ---------------------------------------------------------------------------------------- PDFs

    private List<Batch> ocrPdf(byte[] pdf, Usage usage) throws IOException {
        List<Batch> out = new ArrayList<>();
        try (PDDocument doc = Loader.loadPDF(pdf)) {
            int n = doc.getNumberOfPages();
            for (int start = 1; start <= n; start += pagesPerRequest) {
                ocrPages(doc, start, Math.min(n, start + pagesPerRequest - 1), usage, out);
            }
        }
        return out;
    }

    /** OCR pages [first, last] (1-based), halving the range when it is too big or gets truncated. */
    private void ocrPages(PDDocument doc, int first, int last, Usage usage, List<Batch> out) throws IOException {
        byte[] part = extract(doc, first, last);
        int pages = last - first + 1;
        if (part.length > maxRequestBytes && pages > 1) {
            int mid = first + pages / 2 - 1;
            ocrPages(doc, first, mid, usage, out);
            ocrPages(doc, mid + 1, last, usage, out);
            return;
        }
        BetaContentBlockParam block;
        if (part.length > maxRequestBytes) {
            // One oversized page: send a rendered image of it instead.
            BufferedImage img = new PDFRenderer(doc).renderImageWithDPI(first - 1, renderDpi);
            block = imageBlock(png(scale(img)), BetaBase64ImageSource.MediaType.IMAGE_PNG);
        } else {
            block = BetaContentBlockParam.ofDocument(BetaRequestDocumentBlock.builder()
                    .source(BetaBase64PdfSource.builder().data(Base64.getEncoder().encodeToString(part)).build())
                    .build());
        }
        Batch b = call(block, pages, "pages " + first + "-" + last, usage);
        if (b.outcome() == Outcome.TRUNCATED && pages > 1) {
            int mid = first + pages / 2 - 1;
            ocrPages(doc, first, mid, usage, out);
            ocrPages(doc, mid + 1, last, usage, out);
            return;
        }
        out.add(b);
    }

    private static byte[] extract(PDDocument doc, int first, int last) throws IOException {
        try (PDDocument part = new PageExtractor(doc, first, last).extract()) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            part.save(bos);
            return bos.toByteArray();
        }
    }

    // -------------------------------------------------------------------------------------- images

    private Batch ocrImage(byte[] bytes, String form, Usage usage) throws IOException {
        byte[] data = bytes;
        BetaBase64ImageSource.MediaType type = mediaType(form);
        BufferedImage img = ImageIO.read(new ByteArrayInputStream(bytes));
        boolean tooBig = base64Length(bytes.length) > 10L * 1024 * 1024;
        if (img != null && (type == null || tooBig || Math.max(img.getWidth(), img.getHeight()) > maxLongEdge)) {
            data = png(scale(img));
            type = BetaBase64ImageSource.MediaType.IMAGE_PNG;
        } else if (type == null || tooBig) {
            throw new IOException("unsupported or oversized image (" + form + ", " + bytes.length + " bytes)");
        }
        return call(imageBlock(data, type), 1, "image", usage);
    }

    private static BetaBase64ImageSource.MediaType mediaType(String form) {
        if (!IMAGE_FORMS_DIRECT.contains(form)) {
            return null; // e.g. TIFF, BMP: converted to PNG
        }
        switch (form) {
            case "IMAGE_PNG":
                return BetaBase64ImageSource.MediaType.IMAGE_PNG;
            case "IMAGE_JPEG":
                return BetaBase64ImageSource.MediaType.IMAGE_JPEG;
            case "IMAGE_GIF":
                return BetaBase64ImageSource.MediaType.IMAGE_GIF;
            default:
                return BetaBase64ImageSource.MediaType.IMAGE_WEBP;
        }
    }

    private BufferedImage scale(BufferedImage img) {
        int longEdge = Math.max(img.getWidth(), img.getHeight());
        if (longEdge <= maxLongEdge) {
            return img;
        }
        double f = (double) maxLongEdge / longEdge;
        int w = Math.max(1, (int) Math.round(img.getWidth() * f));
        int h = Math.max(1, (int) Math.round(img.getHeight() * f));
        BufferedImage out = new BufferedImage(w, h, BufferedImage.TYPE_INT_RGB);
        out.getGraphics().drawImage(img.getScaledInstance(w, h, Image.SCALE_SMOOTH), 0, 0, null);
        return out;
    }

    private static byte[] png(BufferedImage img) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        ImageIO.write(img, "png", bos);
        return bos.toByteArray();
    }

    private static long base64Length(long n) {
        return 4 * ((n + 2) / 3);
    }

    private static BetaContentBlockParam imageBlock(byte[] data, BetaBase64ImageSource.MediaType type) {
        return BetaContentBlockParam.ofImage(BetaImageBlockParam.builder()
                .source(BetaBase64ImageSource.builder().data(Base64.getEncoder().encodeToString(data)).mediaType(type).build())
                .build());
    }

    // ------------------------------------------------------------------------------------- the call

    private Batch call(BetaContentBlockParam media, int pages, String label, Usage usage) {
        MessageCreateParams params = MessageCreateParams.builder()
                .model(model)
                .maxTokens(maxTokens)
                .outputConfig(BetaOutputConfig.builder().effort(effort).build())
                // Server-side refusal fallbacks: a refused request is retried on another model by the API.
                .addBeta(AnthropicBeta.SERVER_SIDE_FALLBACK_2026_07_01)
                .fallbacksDefault()
                .addUserMessageOfBetaContentBlockParams(List.of(media, BetaContentBlockParam.ofText(prompt)))
                .build();
        BetaMessage msg;
        try {
            msg = client.beta().messages().create(params);
        } catch (AnthropicException e) {
            usage.requests++;
            return new Batch(Outcome.ERROR, "", pages, label + ": " + e.getClass().getSimpleName() + ": " + e.getMessage());
        }
        usage.requests++;
        usage.input += msg.usage().inputTokens();
        usage.output += msg.usage().outputTokens();
        usage.models.add(msg.model().asString());

        StringBuilder text = new StringBuilder();
        for (BetaContentBlock block : msg.content()) {
            block.text().ifPresent(t -> text.append(text.length() == 0 ? "" : "\n").append(t.text()));
        }
        BetaStopReason reason = msg.stopReason().orElse(null);
        if (BetaStopReason.END_TURN.equals(reason) || BetaStopReason.STOP_SEQUENCE.equals(reason)) {
            return new Batch(Outcome.COMPLETE, text.toString(), pages, label);
        }
        if (BetaStopReason.MAX_TOKENS.equals(reason)) {
            return new Batch(Outcome.TRUNCATED, text.toString(), pages, label + ": hit max_tokens " + maxTokens);
        }
        if (BetaStopReason.REFUSAL.equals(reason)) {
            String detail = msg.stopDetails().map(sd -> sd.category().map(c -> c.asString()).orElse("unspecified")
                    + sd.explanation().map(x -> ": " + x).orElse("")).orElse("unspecified");
            return new Batch(Outcome.REFUSED, text.toString(), pages, label + ": refused (" + detail + ")");
        }
        return new Batch(Outcome.TRUNCATED, text.toString(), pages, label + ": unexpected stop_reason " + reason);
    }

    // ------------------------------------------------------------------------------------- results

    private void record(IBaseDataObject d, List<Batch> batches, Usage usage) {
        StringBuilder all = new StringBuilder();
        int pages = 0;
        Set<Outcome> seen = new LinkedHashSet<>();
        for (Batch b : batches) {
            seen.add(b.outcome());
            pages += b.pages();
            if (batches.size() > 1) {
                all.append("\n\n<!-- ").append(b.detail().split(":")[0]).append(" -->\n");
            }
            all.append(b.text());
            if (b.outcome() != Outcome.COMPLETE) {
                d.addProcessingError("ClaudeOcrPlace: " + b.outcome() + " " + b.detail());
                // Emissary's JSON output omits processing errors, so keep the reason in a parameter too.
                d.appendParameter("OCR_DETAIL", b.outcome() + " " + b.detail());
            }
        }
        String text = all.toString().strip();
        if (!text.isEmpty()) {
            d.addAlternateView(OCR_VIEW, text.getBytes(StandardCharsets.UTF_8));
        }
        d.putParameter("OCR_STATUS", rollUpName(seen));
        d.putParameter("OCR_PAGES", pages);
        d.putParameter("OCR_REQUESTS", usage.requests);
        d.putParameter("OCR_INPUT_TOKENS", usage.input);
        d.putParameter("OCR_OUTPUT_TOKENS", usage.output);
        d.putParameter("OCR_MODEL_REQUESTED", model);
        if (!usage.models.isEmpty()) {
            d.putParameter("OCR_MODEL", String.join(",", usage.models)); // differs from requested if a fallback served it
        }
        d.putParameter("OCR_TEXT_CHARS", text.length());
    }

    /** COMPLETE, TRUNCATED, REFUSED or ERROR when uniform; PARTIAL when batches differ. */
    static String rollUpName(Set<Outcome> seen) {
        if (seen.isEmpty()) {
            return Outcome.ERROR.name();
        }
        return seen.size() == 1 ? seen.iterator().next().name() : "PARTIAL";
    }

    private static long parseLong(String s, long dflt) {
        try {
            return s == null ? dflt : Long.parseLong(s.trim());
        } catch (NumberFormatException e) {
            return dflt;
        }
    }
}
