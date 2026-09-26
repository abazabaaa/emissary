package demo.places;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import emissary.core.DataObjectFactory;
import emissary.core.IBaseDataObject;
import emissary.test.core.junit5.UnitTest;

/** Uses real forked Tika JVMs, shared across the tests in this class (fork start-up takes seconds). */
class TikaTextPlaceTest extends UnitTest {

    private static TikaTextPlace place;

    @BeforeAll
    static void startPlace() throws Exception {
        setupSystemProperties();
        try (InputStream cfg = Fixtures.config("TikaTextPlace")) {
            place = new TikaTextPlace(cfg, "http://localhost:8001/TikaTextPlace");
        }
    }

    @AfterAll
    static void stopPlace() {
        place.shutDown();
    }

    @Override
    @BeforeEach
    public void setUp() {}

    @Override
    @AfterEach
    public void tearDown() throws Exception {
        // The fork pool's threads outlive each test on purpose; skip UnitTest's thread-count check.
        restoreConfig();
    }

    private static IBaseDataObject run(byte[] bytes, String name, String form) {
        IBaseDataObject d = DataObjectFactory.getInstance(bytes, "/input/" + name, form);
        d.putParameter(TikaIdPlace.ORIGINAL_FILENAME, name);
        place.process(d);
        return d;
    }

    private static String textView(IBaseDataObject d) {
        byte[] v = d.getAlternateView(TikaTextPlace.TEXT_VIEW);
        return v == null ? null : new String(v, StandardCharsets.UTF_8);
    }

    @Test
    void htmlTextTitleAndAuthor() {
        IBaseDataObject d = run(Fixtures.utf8("<html><head><title>Q3 Contract</title><meta name='author' content='Jo Smith'></head>"
                + "<body><h1>Contract</h1><p>The Q3 contract with Acme Corporation is due on Friday and payment "
                + "terms are thirty days from the invoice date.</p></body></html>"), "page.html", "HTML");
        String text = textView(d);
        assertTrue(text.contains("# Contract"), "Markdown heading expected: " + text);
        assertTrue(text.contains("Acme Corporation"));
        assertEquals("Q3 Contract", d.getStringParameter("TITLE"));
        assertEquals("Jo Smith", d.getStringParameter("AUTHOR"));
        assertEquals("eng", d.getStringParameter("LANGUAGE")); // Tika 4 CharSoup reports ISO 639-3 codes
        assertEquals("OK", d.getStringParameter("TIKA_STATUS"));
        assertEquals("HTML", d.currentForm(), "ANALYZE must not change the form");
    }

    @Test
    void pdfTextAndPageCount() {
        IBaseDataObject d = run(Fixtures.pdf("Board Minutes", "Minutes of the board meeting"), "minutes.pdf", "PDF");
        assertTrue(textView(d).contains("Minutes of the board meeting"), textView(d));
        assertEquals("Board Minutes", d.getStringParameter("TITLE"));
        assertEquals("1", d.getStringParameter(TikaTextPlace.PAGE_COUNT));
        assertTrue(Integer.parseInt(d.getStringParameter(TikaTextPlace.TEXT_CHARS)) > 10);
    }

    @Test
    void imageHasNoTextSoOcrCanDecide() {
        IBaseDataObject d = run(Fixtures.PNG_1X1, "pixel.png", "IMAGE_PNG");
        assertNull(textView(d));
        assertEquals("0", d.getStringParameter(TikaTextPlace.TEXT_CHARS));
    }

    @Test
    void containersAreSkipped() throws Exception {
        IBaseDataObject d = run(Fixtures.zip(Fixtures.entries("a.txt", "hello")), "bundle.zip", UnzipPlace.UNWRAPPED);
        assertFalse(d.hasParameter("TIKA_STATUS"));
    }

    @Test
    void payloadBytesUnchanged() {
        byte[] original = Fixtures.utf8("plain text stays exactly as it was");
        IBaseDataObject d = run(original.clone(), "notes.txt", "TEXT");
        assertEquals(new String(original, StandardCharsets.UTF_8), new String(d.data(), StandardCharsets.UTF_8));
    }
}
