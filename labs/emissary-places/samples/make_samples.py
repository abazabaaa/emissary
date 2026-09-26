#!/usr/bin/env python3
"""Build the demo input set (or, with --bench N, a mixed corpus of N files for benchmarking)."""
import argparse
import os
import io
import pathlib
import random
import shutil
import subprocess
import zipfile


def pdf(title, lines):
    """Minimal valid text PDF (one page)."""
    text = " ".join(f"({l}) Tj T*" for l in lines)
    stream = f"BT /F1 12 Tf 14 TL 72 720 Td {text} ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Title ({title}) /Author (Dana Reyes) >>",
    ]
    out, offsets = "%PDF-1.4\n", []
    for i, o in enumerate(objs):
        offsets.append(len(out))
        out += f"{i + 1} 0 obj\n{o}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 6 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


def scanned_pdf():
    """A PDF whose only content is an image (no text layer), like a scan."""
    from PIL import Image, ImageDraw  # noqa: only needed for this sample
    img = Image.new("RGB", (1275, 1650), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(["SETTLEMENT AGREEMENT", "Party A: Acme Corporation", "Party B: Globex LLC",
                              "Amount: $250,000", "Signed: March 3, 2026"]):
        d.text((120, 150 + i * 60), line, fill="black")
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=150)
    return buf.getvalue()


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


HTML = ("<html><head><title>Q3 Vendor Review</title><meta name='author' content='Sam Park'></head><body>"
        "<h1>Q3 Vendor Review</h1><p>Acme Corporation delivered 94% of orders on time this quarter. "
        "The contract renewal is due on Friday, and legal has asked for the indemnity clause to be revised.</p>"
        "<table><tr><th>Vendor</th><th>On time</th></tr><tr><td>Acme</td><td>94%</td></tr>"
        "<tr><td>Globex</td><td>88%</td></tr></table></body></html>")
NOTES = "meeting notes: the q3 contract with acme is due friday. follow up with legal about the indemnity clause.\n"
MEMO_ES = "Memorando: la reunión con el proveedor se trasladó al jueves. Por favor confirme su asistencia antes del martes.\n"


def demo(out):
    inv = '{"customer":"Acme","invoice":"INV-2026-0042","amount":1200,"currency":"USD"}\n'
    files = {
        "notes.txt": NOTES.encode(),
        "invoice.json": inv.encode(),
        "bundle.zip": zip_bytes({"notes.txt": NOTES, "invoice.json": inv}),
        "nested.zip": zip_bytes({
            "review/vendor-review.html": HTML,
            "review/board-minutes.pdf": pdf("Board Minutes", ["Minutes of the board meeting, 12 August 2026.",
                                                              "The board approved the Acme contract renewal."]),
            "archive/older.zip": zip_bytes({"memo-es.txt": MEMO_ES}),
        }),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
    knight = pathlib.Path(os.environ.get("EMISSARY_HOME", pathlib.Path(__file__).resolve().parents[3])) / "emissary-knight.png"
    if knight.exists():  # any PNG works; Emissary's logo is just a convenient one
        shutil.copy(knight, out / "knight.png")
    else:
        print(f"{knight} not found; skipping knight.png (set EMISSARY_HOME)")
    # Real ZipCrypto-encrypted archive via the zip CLI
    tmp = out.parent / "_secret"
    tmp.mkdir(exist_ok=True)
    (tmp / "secret.txt").write_text("privileged: attorney-client communication\n")
    subprocess.run(["zip", "-q", "-j", "-P", "hunter2", str(out / "locked.zip"), str(tmp / "secret.txt")], check=True)
    shutil.rmtree(tmp)
    try:
        (out / "scanned-agreement.pdf").write_bytes(scanned_pdf())
    except ImportError:
        print("Pillow not installed; skipping scanned-agreement.pdf")


def bench(out, n):
    rnd = random.Random(7)
    words = (NOTES + HTML + MEMO_ES).replace("<", " ").replace(">", " ").split()
    for i in range(n):
        kind = i % 5
        body = " ".join(rnd.choice(words) for _ in range(400))
        if kind == 0:
            (out / f"doc{i:04d}.txt").write_text(body)
        elif kind == 1:
            (out / f"doc{i:04d}.html").write_text(f"<html><head><title>Doc {i}</title></head><body><p>{body}</p></body></html>")
        elif kind == 2:
            (out / f"doc{i:04d}.pdf").write_bytes(pdf(f"Doc {i}", [body[j:j + 80] for j in range(0, 800, 80)]))
        elif kind == 3:
            (out / f"doc{i:04d}.json").write_text('{"id": %d, "text": "%s"}' % (i, body))
        else:
            (out / f"doc{i:04d}.zip").write_bytes(zip_bytes({f"a{i}.txt": body, f"b{i}.html": f"<p>{body}</p>"}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--bench", type=int)
    a = ap.parse_args()
    o = pathlib.Path(a.out)
    o.mkdir(parents=True, exist_ok=True)
    bench(o, a.bench) if a.bench else demo(o)
    print(f"wrote {len(list(o.iterdir()))} files to {o}")
