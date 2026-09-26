package demo.places;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

import org.apache.commons.compress.archivers.zip.ZipArchiveEntry;
import org.apache.commons.compress.archivers.zip.ZipFile;
import org.apache.commons.compress.utils.SeekableInMemoryByteChannel;

import emissary.core.DataObjectFactory;
import emissary.core.Family;
import emissary.core.Form;
import emissary.core.IBaseDataObject;
import emissary.place.MultiFileServerPlace;

/**
 * TRANSFORM-stage place that turns a ZIP payload into one child payload per file entry. Children get
 * form UNKNOWN, so they go back through identification; a nested zip comes back here and is unpacked
 * in turn. The parent is re-labelled so it doesn't route here again:
 * <ul>
 * <li>ZIP-UNWRAPPED: at least one entry extracted</li>
 * <li>ZIP-PASSWORD-PROTECTED: only encrypted entries</li>
 * <li>ZIP-BROKEN: the archive could not be read</li>
 * </ul>
 * Limits on entry count and sizes guard against zip bombs; anything skipped is recorded on the parent.
 */
public class UnzipPlace extends MultiFileServerPlace {

    public static final String UNWRAPPED = "ZIP" + Form.SUFFIXES_UNWRAPPED;
    public static final String PASSWORD_PROTECTED = "ZIP" + Form.SUFFIXES_PASSWORD_PROTECTED;
    public static final String BROKEN = "ZIP" + Form.SUFFIXES_BROKEN;

    private int maxEntries;
    private long maxEntryBytes;
    private long maxTotalBytes;

    public UnzipPlace(String configInfo, String dir, String placeLoc) throws IOException {
        super(configInfo, dir, placeLoc);
        configurePlace(); // MultiFileServerPlace declares this but leaves calling it to subclasses
    }

    public UnzipPlace(InputStream configInfo, String placeLoc) throws IOException {
        super(configInfo, placeLoc);
        configurePlace();
    }

    @Override
    protected void configurePlace() {
        maxEntries = configG.findIntEntry("MAX_ENTRIES", 1000);
        maxEntryBytes = configG.findLongEntry("MAX_ENTRY_BYTES", 256L * 1024 * 1024);
        maxTotalBytes = configG.findLongEntry("MAX_TOTAL_BYTES", 1024L * 1024 * 1024);
    }

    @Override
    public List<IBaseDataObject> processHeavyDuty(IBaseDataObject parent) {
        List<IBaseDataObject> children = new ArrayList<>();
        int encrypted = 0;
        int skipped = 0;
        long total = 0;
        int birthOrder = parent.getNumChildren();

        try (ZipFile zip = ZipFile.builder().setSeekableByteChannel(new SeekableInMemoryByteChannel(parent.data())).get()) {
            for (ZipArchiveEntry entry : Collections.list(zip.getEntriesInPhysicalOrder())) {
                if (entry.isDirectory()) {
                    continue;
                }
                if (entry.getGeneralPurposeBit().usesEncryption()) {
                    encrypted++;
                    continue;
                }
                if (!zip.canReadEntryData(entry)) {
                    skipped++;
                    parent.addProcessingError("UnzipPlace: unsupported compression for " + entry.getName());
                    continue;
                }
                if (children.size() >= maxEntries) {
                    skipped++;
                    parent.addProcessingError("UnzipPlace: MAX_ENTRIES " + maxEntries + " reached, skipped " + entry.getName());
                    continue;
                }
                byte[] bytes;
                try (InputStream in = zip.getInputStream(entry)) {
                    bytes = readLimited(in, Math.min(maxEntryBytes, maxTotalBytes - total));
                }
                if (bytes == null) {
                    skipped++;
                    parent.addProcessingError("UnzipPlace: size limit exceeded, skipped " + entry.getName());
                    continue;
                }
                total += bytes.length;
                birthOrder++;
                IBaseDataObject child = DataObjectFactory.getInstance(bytes, parent.getFilename() + Family.getSep(birthOrder), Form.UNKNOWN);
                child.putParameter("ZIP_ENTRY_PATH", entry.getName());
                child.putParameter(TikaIdPlace.ORIGINAL_FILENAME, baseName(entry.getName()));
                if (entry.getTime() != -1) {
                    child.putParameter("ZIP_ENTRY_DATE", Instant.ofEpochMilli(entry.getTime()).toString());
                }
                children.add(child);
            }
        } catch (IOException | RuntimeException e) {
            parent.addProcessingError("UnzipPlace: cannot read archive: " + e);
            if (children.isEmpty()) {
                parent.replaceCurrentForm(BROKEN);
                return Collections.emptyList();
            }
        }

        parent.putParameter("ZIP_ENTRIES_EXTRACTED", children.size());
        if (encrypted > 0) {
            parent.putParameter("ZIP_ENTRIES_ENCRYPTED", encrypted);
        }
        if (skipped > 0) {
            parent.putParameter("ZIP_ENTRIES_SKIPPED", skipped);
        }
        parent.replaceCurrentForm(children.isEmpty() && encrypted > 0 ? PASSWORD_PROTECTED : UNWRAPPED);
        if (!children.isEmpty()) {
            addParentInformation(parent, children);
        }
        return children;
    }

    /** Reads at most {@code limit} bytes; returns null if the entry is larger. */
    private static byte[] readLimited(InputStream in, long limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[64 * 1024];
        long seen = 0;
        int n;
        while ((n = in.read(buf)) != -1) {
            seen += n;
            if (seen > limit) {
                return null;
            }
            out.write(buf, 0, n);
        }
        return out.toByteArray();
    }

    private static String baseName(String path) {
        int slash = Math.max(path.lastIndexOf('/'), path.lastIndexOf('\\'));
        return path.substring(slash + 1);
    }
}
