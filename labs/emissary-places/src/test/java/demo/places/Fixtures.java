package demo.places;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Test inputs built in code, so the tests carry no binary fixtures. */
final class Fixtures {

    private Fixtures() {}

    static InputStream config(String place) {
        InputStream in = Fixtures.class.getResourceAsStream("/demo/places/" + place + ".cfg");
        if (in == null) {
            throw new IllegalStateException("missing config for " + place);
        }
        return in;
    }

    static byte[] utf8(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }

    static Map<String, byte[]> entries(Object... nameThenBytes) {
        Map<String, byte[]> m = new LinkedHashMap<>();
        for (int i = 0; i < nameThenBytes.length; i += 2) {
            Object v = nameThenBytes[i + 1];
            m.put((String) nameThenBytes[i], v instanceof String ? utf8((String) v) : (byte[]) v);
        }
        return m;
    }

    static byte[] zip(Map<String, byte[]> files) throws IOException {
        return zip(files, false);
    }

    /** With stored=true entries are uncompressed, which makes the header patching in encrypted() safe. */
    static byte[] zip(Map<String, byte[]> files, boolean stored) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        try (ZipOutputStream zos = new ZipOutputStream(bos)) {
            for (Map.Entry<String, byte[]> f : files.entrySet()) {
                ZipEntry e = new ZipEntry(f.getKey());
                if (stored) {
                    CRC32 crc = new CRC32();
                    crc.update(f.getValue());
                    e.setMethod(ZipEntry.STORED);
                    e.setSize(f.getValue().length);
                    e.setCompressedSize(f.getValue().length);
                    e.setCrc(crc.getValue());
                }
                zos.putNextEntry(e);
                zos.write(f.getValue());
                zos.closeEntry();
            }
        }
        return bos.toByteArray();
    }

    /**
     * A zip whose entries are flagged encrypted (general-purpose bit 0 set in the local and central
     * headers). java.util.zip can't write encrypted zips; the flag is all UnzipPlace looks at.
     */
    static byte[] encrypted(Map<String, byte[]> files) throws IOException {
        byte[] z = zip(files, true);
        for (int i = 0; i + 4 <= z.length; i++) {
            int sig = (z[i] & 0xff) | (z[i + 1] & 0xff) << 8 | (z[i + 2] & 0xff) << 16 | (z[i + 3] & 0xff) << 24;
            if (sig == 0x04034b50) {
                z[i + 6] |= 1; // local file header: general purpose flag
            } else if (sig == 0x02014b50) {
                z[i + 8] |= 1; // central directory header: general purpose flag
            }
        }
        return z;
    }

    /** Smallest valid one-page PDF with the given text, built by hand with a correct xref table. */
    static byte[] pdf(String title, String text) {
        String stream = "BT /F1 18 Tf 72 720 Td (" + text + ") Tj ET";
        String[] objs = {
                "<< /Type /Catalog /Pages 2 0 R >>",
                "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
                "<< /Length " + stream.length() + " >>\nstream\n" + stream + "\nendstream",
                "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
                "<< /Title (" + title + ") /Author (Jo Smith) >>"
        };
        StringBuilder sb = new StringBuilder("%PDF-1.4\n");
        int[] offsets = new int[objs.length];
        for (int i = 0; i < objs.length; i++) {
            offsets[i] = sb.length();
            sb.append(i + 1).append(" 0 obj\n").append(objs[i]).append("\nendobj\n");
        }
        int xref = sb.length();
        sb.append("xref\n0 ").append(objs.length + 1).append("\n0000000000 65535 f \n");
        for (int off : offsets) {
            sb.append(String.format("%010d 00000 n \n", off));
        }
        sb.append("trailer\n<< /Size ").append(objs.length + 1).append(" /Root 1 0 R /Info 6 0 R >>\nstartxref\n")
                .append(xref).append("\n%%EOF\n");
        return sb.toString().getBytes(StandardCharsets.ISO_8859_1);
    }

    static final byte[] PNG_1X1 = java.util.Base64.getDecoder().decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==");
}
