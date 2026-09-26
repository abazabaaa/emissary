package demo.places;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import emissary.core.DataObjectFactory;
import emissary.core.Form;
import emissary.core.IBaseDataObject;
import emissary.test.core.junit5.UnitTest;

class UnzipPlaceTest extends UnitTest {

    private UnzipPlace place;

    @Override
    @BeforeEach
    public void setUp() throws Exception {
        place = newPlace("");
    }

    private UnzipPlace newPlace(String extraConfig) throws Exception {
        String base;
        try (InputStream cfg = Fixtures.config("UnzipPlace")) {
            base = new String(cfg.readAllBytes(), StandardCharsets.UTF_8);
        }
        return new UnzipPlace(new ByteArrayInputStream((extraConfig + "\n" + base) /* first value of a key wins */.getBytes(StandardCharsets.UTF_8)),
                "http://localhost:8001/UnzipPlace");
    }

    @Override
    @AfterEach
    public void tearDown() throws Exception {
        place.shutDown();
        super.tearDown();
    }

    private static IBaseDataObject zipPayload(byte[] zip) {
        return DataObjectFactory.getInstance(zip, "/input/bundle.zip", "ZIP");
    }

    @Test
    void extractsEachEntryAsUnknownChild() throws Exception {
        IBaseDataObject parent = zipPayload(Fixtures.zip(Fixtures.entries(
                "notes.txt", "meeting notes", "dir/invoice.json", "{\"a\":1}")));
        List<IBaseDataObject> kids = place.processHeavyDuty(parent);

        assertEquals(2, kids.size());
        assertEquals("/input/bundle.zip-att-1", kids.get(0).getFilename());
        assertEquals("/input/bundle.zip-att-2", kids.get(1).getFilename());
        assertEquals(Form.UNKNOWN, kids.get(0).currentForm());
        assertEquals("meeting notes", new String(kids.get(0).data(), StandardCharsets.UTF_8));
        assertEquals("dir/invoice.json", kids.get(1).getStringParameter("ZIP_ENTRY_PATH"));
        assertEquals("invoice.json", kids.get(1).getStringParameter(TikaIdPlace.ORIGINAL_FILENAME));
        assertTrue(kids.get(0).hasParameter("ZIP_ENTRY_DATE"));
        assertEquals(UnzipPlace.UNWRAPPED, parent.currentForm());
        assertEquals("2", parent.getStringParameter("ZIP_ENTRIES_EXTRACTED"));
    }

    @Test
    void nestedZipBecomesAChildForTheNextPass() throws Exception {
        byte[] inner = Fixtures.zip(Fixtures.entries("deep.txt", "deep"));
        IBaseDataObject parent = zipPayload(Fixtures.zip(Fixtures.entries("inner.zip", inner)));
        List<IBaseDataObject> kids = place.processHeavyDuty(parent);
        assertEquals(1, kids.size());

        // Second pass, as the workflow would do after the child is identified as ZIP.
        IBaseDataObject child = kids.get(0);
        child.replaceCurrentForm("ZIP");
        List<IBaseDataObject> grandKids = place.processHeavyDuty(child);
        assertEquals("/input/bundle.zip-att-1-att-1", grandKids.get(0).getFilename());
    }

    @Test
    void encryptedEntriesAreFlaggedNotExtracted() throws Exception {
        IBaseDataObject parent = zipPayload(Fixtures.encrypted(Fixtures.entries("secret.txt", "classified")));
        assertTrue(place.processHeavyDuty(parent).isEmpty());
        assertEquals(UnzipPlace.PASSWORD_PROTECTED, parent.currentForm());
        assertEquals("1", parent.getStringParameter("ZIP_ENTRIES_ENCRYPTED"));
    }

    @Test
    void garbageIsBroken() {
        IBaseDataObject parent = zipPayload("PK\u0003\u0004 this is not really a zip".getBytes(StandardCharsets.ISO_8859_1));
        assertTrue(place.processHeavyDuty(parent).isEmpty());
        assertEquals(UnzipPlace.BROKEN, parent.currentForm());
        assertTrue(parent.getProcessingError().contains("cannot read archive"));
    }

    @Test
    void limitsStopZipBombs() throws Exception {
        place.shutDown();
        place = newPlace("MAX_ENTRIES = 2\nMAX_ENTRY_BYTES = 100\n");
        IBaseDataObject parent = zipPayload(Fixtures.zip(Fixtures.entries(
                "a.txt", "a", "big.bin", new byte[500], "b.txt", "b", "c.txt", "c")));
        List<IBaseDataObject> kids = place.processHeavyDuty(parent);
        assertEquals(2, kids.size()); // a.txt and b.txt; big.bin too large, c.txt over the count
        assertEquals("2", parent.getStringParameter("ZIP_ENTRIES_SKIPPED"));
        assertEquals(UnzipPlace.UNWRAPPED, parent.currentForm());
    }
}
