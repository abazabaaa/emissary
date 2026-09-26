package demo.places;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.io.InputStream;
import java.util.Random;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.api.Test;

import emissary.core.DataObjectFactory;
import emissary.core.Form;
import emissary.core.IBaseDataObject;
import emissary.test.core.junit5.UnitTest;

class TikaIdPlaceTest extends UnitTest {

    private TikaIdPlace place;

    @Override
    @BeforeEach
    public void setUp() throws Exception {
        try (InputStream cfg = Fixtures.config("TikaIdPlace")) {
            place = new TikaIdPlace(cfg, "http://localhost:8001/TikaIdPlace");
        }
    }

    @Override
    @AfterEach
    public void tearDown() throws Exception {
        place.shutDown();
        super.tearDown();
    }

    private IBaseDataObject run(byte[] bytes, String name) {
        IBaseDataObject d = DataObjectFactory.getInstance(bytes, "/input/" + name, Form.UNKNOWN);
        place.process(d);
        return d;
    }

    @ParameterizedTest
    @CsvSource({
            "notes.txt, meeting notes: the q3 contract is due friday., TEXT",
            "invoice.json, '{\"customer\":\"Acme\",\"amount\":1200}', JSON_TEXT",
            "page.html, <html><head><title>t</title></head><body><p>hi</p></body></html>, HTML"})
    void identifiesTextFormats(String name, String content, String form) {
        IBaseDataObject d = run(Fixtures.utf8(content), name);
        assertEquals(form, d.currentForm());
        assertEquals(form, d.getFileType());
    }

    @Test
    void identifiesZipPdfAndPng() throws Exception {
        assertEquals("ZIP", run(Fixtures.zip(Fixtures.entries("a.txt", "hello")), "bundle.zip").currentForm());
        IBaseDataObject pdf = run(Fixtures.pdf("Probe", "Hello PDF"), "doc.pdf");
        assertEquals("PDF", pdf.currentForm());
        assertEquals("application/pdf", pdf.getStringParameter(TikaIdPlace.MIME_TYPE));
        assertEquals("IMAGE_PNG", run(Fixtures.PNG_1X1, "pixel.png").currentForm());
    }

    @Test
    void usesOriginalFilenameForExtractedChildren() {
        IBaseDataObject d = DataObjectFactory.getInstance(Fixtures.utf8("{\"a\":1}"), "/input/bundle.zip-att-2", Form.UNKNOWN);
        d.putParameter(TikaIdPlace.ORIGINAL_FILENAME, "data.json");
        place.process(d);
        assertEquals("JSON_TEXT", d.currentForm());
    }

    @Test
    void leavesRandomBytesUnknown() {
        byte[] noise = new byte[4096];
        new Random(42).nextBytes(noise);
        assertEquals(Form.UNKNOWN, run(noise, "blob").currentForm());
    }
}
