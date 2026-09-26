package demo.places;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import javax.imageio.ImageIO;

import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.pdmodel.PDPage;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import emissary.core.DataObjectFactory;
import emissary.core.IBaseDataObject;
import emissary.test.core.junit5.UnitTest;

/** Exercises ClaudeOcrPlace against a local stub of the Messages API: no network, no spend. */
class ClaudeOcrPlaceTest extends UnitTest {

    private StubMessagesApi api;
    private ClaudeOcrPlace place;

    @Override
    @BeforeEach
    public void setUp() throws Exception {
        api = new StubMessagesApi();
        System.setProperty("demo.ocr.apiKey", "test-key");
        place = newPlace("OCR_ENABLED = \"true\"\nAPI_BASE_URL = \"" + api.baseUrl() + "\"\nPAGES_PER_REQUEST = 4\n");
    }

    private static ClaudeOcrPlace newPlace(String overrides) throws Exception {
        String base;
        try (InputStream cfg = Fixtures.config("ClaudeOcrPlace")) {
            base = new String(cfg.readAllBytes(), StandardCharsets.UTF_8);
        }
        // First value of a key wins in Emissary config, so overrides go first.
        return new ClaudeOcrPlace(new ByteArrayInputStream((overrides + "\n" + base).getBytes(StandardCharsets.UTF_8)),
                "http://localhost:8001/ClaudeOcrPlace");
    }

    @Override
    @AfterEach
    public void tearDown() throws Exception {
        place.shutDown();
        api.close();
        System.clearProperty("demo.ocr.apiKey");
        super.tearDown();
    }

    private static IBaseDataObject scannedPdf(int pages) throws Exception {
        try (PDDocument doc = new PDDocument()) {
            for (int i = 0; i < pages; i++) {
                doc.addPage(new PDPage());
            }
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            doc.save(bos);
            IBaseDataObject d = DataObjectFactory.getInstance(bos.toByteArray(), "/input/scan.pdf", "PDF");
            d.putParameter(TikaTextPlace.TEXT_CHARS, 0); // what TikaTextPlace reports for a scan
            d.putParameter(TikaTextPlace.PAGE_COUNT, pages);
            return d;
        }
    }

    private static String view(IBaseDataObject d) {
        byte[] v = d.getAlternateView(ClaudeOcrPlace.OCR_VIEW);
        return v == null ? null : new String(v, StandardCharsets.UTF_8);
    }

    @Test
    void imageTranscribedAndRequestShapeIsRight() {
        api.then(StubMessagesApi.thinkingThenText("INVOICE #42\nTotal: $1,200"));
        IBaseDataObject d = DataObjectFactory.getInstance(Fixtures.PNG_1X1, "/input/receipt.png", "IMAGE_PNG");
        place.process(d);

        assertEquals("INVOICE #42\nTotal: $1,200", view(d), "thinking block must be ignored");
        assertEquals("COMPLETE", d.getStringParameter("OCR_STATUS"));
        assertEquals("1", d.getStringParameter("OCR_REQUESTS"));
        assertEquals("1000", d.getStringParameter("OCR_INPUT_TOKENS"));
        assertEquals("claude-opus-5", d.getStringParameter("OCR_MODEL"));

        StubMessagesApi.Request r = api.requests.get(0);
        assertTrue(r.body().contains("\"model\":\"claude-opus-5\""), r.body());
        assertTrue(r.body().contains("\"max_tokens\":16000"));
        assertTrue(r.body().contains("\"effort\":\"medium\""));
        assertTrue(r.body().contains("\"fallbacks\":\"default\""));
        assertTrue(r.headers().get("anthropic-beta").contains("server-side-fallback-2026-07-01"));
        assertTrue(r.body().indexOf("\"type\":\"image\"") < r.body().indexOf("\"type\":\"text\""), "media before prompt");
        assertFalse(r.body().contains("temperature"), "sampling params are rejected on Opus 5");
        assertEquals("test-key", r.headers().get("x-api-key"));
    }

    @Test
    void pdfIsBatchedByPages() throws Exception {
        api.then(StubMessagesApi.text("end_turn", "pages one to four")).then(StubMessagesApi.text("end_turn", "pages five and six"));
        IBaseDataObject d = scannedPdf(6);
        place.process(d);

        assertEquals(2, api.requests.size(), "6 pages at 4 per request");
        assertTrue(api.requests.get(0).body().contains("\"type\":\"document\""));
        assertEquals(4, pagesSent(api.requests.get(0).body()));
        assertEquals(2, pagesSent(api.requests.get(1).body()));
        assertTrue(view(d).contains("pages one to four") && view(d).contains("pages five and six"));
        assertEquals("6", d.getStringParameter("OCR_PAGES"));
        assertEquals("COMPLETE", d.getStringParameter("OCR_STATUS"));
    }

    @Test
    void truncatedBatchIsSplitAndRetried() throws Exception {
        api.then(StubMessagesApi.text("max_tokens", "partial..."))
                .then(StubMessagesApi.text("end_turn", "first half"))
                .then(StubMessagesApi.text("end_turn", "second half"));
        IBaseDataObject d = scannedPdf(4);
        place.process(d);

        assertEquals(3, api.requests.size());
        assertEquals(2, pagesSent(api.requests.get(1).body()));
        assertEquals("COMPLETE", d.getStringParameter("OCR_STATUS"));
        assertFalse(view(d).contains("partial..."), "truncated text is replaced by the split results");
    }

    @Test
    void singlePageStillTruncatedIsFlaggedNotHidden() throws Exception {
        api.then(StubMessagesApi.text("max_tokens", "a very dense page..."));
        IBaseDataObject d = scannedPdf(1);
        place.process(d);
        assertEquals("TRUNCATED", d.getStringParameter("OCR_STATUS"));
        assertTrue(view(d).contains("a very dense page"));
        assertTrue(d.getProcessingError().contains("max_tokens"));
    }

    @Test
    void imageFormsFromEmissaryMagicAreAccepted() {
        api.then(StubMessagesApi.text("end_turn", "from a PNG form"));
        IBaseDataObject d = DataObjectFactory.getInstance(Fixtures.PNG_1X1, "/input/knight.png", "PNG"); // UnixFilePlace's name
        place.process(d);
        assertEquals("from a PNG form", view(d));
        assertEquals("IMAGE_TIFF", ClaudeOcrPlace.imageForm("TIFF"));
        assertNull(ClaudeOcrPlace.imageForm("TEXT"));
    }

    @Test
    void refusalIsRecordedWithCategory() {
        api.then(StubMessagesApi.refusal("cyber"));
        IBaseDataObject d = DataObjectFactory.getInstance(Fixtures.PNG_1X1, "/input/x.png", "IMAGE_PNG");
        place.process(d);
        assertEquals("REFUSED", d.getStringParameter("OCR_STATUS"));
        assertNull(view(d));
        assertTrue(d.getProcessingError().contains("refused (cyber"), d.getProcessingError());
        assertTrue(d.getStringParameter("OCR_DETAIL").contains("refused (cyber"), "reason must reach the output");
    }

    @Test
    void mixedOutcomesArePartial() throws Exception {
        api.then(StubMessagesApi.text("end_turn", "ok pages")).then(StubMessagesApi.refusal("bio"));
        IBaseDataObject d = scannedPdf(5);
        place.process(d);
        assertEquals("PARTIAL", d.getStringParameter("OCR_STATUS"));
    }

    @Test
    void rateLimitIsRetriedBySdk() {
        api.then(StubMessagesApi.rateLimited()).then(StubMessagesApi.text("end_turn", "after retry"));
        IBaseDataObject d = DataObjectFactory.getInstance(Fixtures.PNG_1X1, "/input/x.png", "IMAGE_PNG");
        place.process(d);
        assertEquals("after retry", view(d));
        assertEquals(2, api.requests.size());
    }

    @Test
    void oversizedImageIsDownscaled() throws Exception {
        BufferedImage big = new BufferedImage(5000, 3000, BufferedImage.TYPE_INT_RGB);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        ImageIO.write(big, "png", bos);
        api.then(StubMessagesApi.text("end_turn", "scaled"));
        IBaseDataObject d = DataObjectFactory.getInstance(bos.toByteArray(), "/input/big.png", "IMAGE_PNG");
        place.process(d);

        Matcher m = Pattern.compile("\"data\":\"([^\"]+)\"").matcher(api.requests.get(0).body());
        assertTrue(m.find());
        BufferedImage sent = ImageIO.read(new ByteArrayInputStream(Base64.getDecoder().decode(m.group(1))));
        assertEquals(2576, Math.max(sent.getWidth(), sent.getHeight()));
    }

    @Test
    void pdfWithRealTextIsNotSent() throws Exception {
        IBaseDataObject d = scannedPdf(2);
        d.putParameter(TikaTextPlace.TEXT_CHARS, 5000);
        place.process(d);
        assertTrue(api.requests.isEmpty());
        assertFalse(d.hasParameter("OCR_STATUS"));
    }

    @Test
    void disabledByDefaultAndWithoutCredentials() throws Exception {
        place.shutDown();
        place = newPlace(""); // OCR_ENABLED defaults to false in the shipped config
        assertFalse(place.isActive());
        place.shutDown();
        System.clearProperty("demo.ocr.apiKey");
        place = newPlace("OCR_ENABLED = \"true\"\n");
        assertEquals(System.getenv("ANTHROPIC_API_KEY") != null, place.isActive());
        IBaseDataObject d = DataObjectFactory.getInstance(Fixtures.PNG_1X1, "/input/x.png", "IMAGE_PNG");
        if (!place.isActive()) {
            place.process(d);
            assertFalse(d.hasParameter("OCR_STATUS"));
        }
    }

    /** Page count of the base64 PDF in a request body. */
    private static int pagesSent(String body) throws Exception {
        Matcher m = Pattern.compile("\"data\":\"([^\"]+)\"").matcher(body);
        assertTrue(m.find());
        try (PDDocument doc = org.apache.pdfbox.Loader.loadPDF(Base64.getDecoder().decode(m.group(1)))) {
            return doc.getNumberOfPages();
        }
    }
}
