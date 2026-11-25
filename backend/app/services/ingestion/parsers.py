"""Turn an uploaded file into a list of `Segment`s: text plus where it came from.

Location metadata is what makes citations possible, so every parser keeps it:
  PDF   -> real page numbers (one segment per page)
  DOCX  -> page numbers from page breaks stored in the file (explicit breaks, and the
           "last rendered page break" markers Word writes on save), plus heading as section.
           A DOCX never opened in Word may have no markers, so everything is page 1.
  TXT   -> pages split on form-feed characters; otherwise page 1, with paragraph blocks
  CSV   -> no pages; each group of rows becomes a segment labelled "Rows 2-26" (header = row 1)
"""
import csv
import io
from dataclasses import dataclass

import docx
from docx.oxml.ns import qn
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class ParseError(Exception):
    pass


@dataclass
class Segment:
    text: str
    page: int | None
    section: str | None = None


@dataclass
class ParsedDocument:
    segments: list[Segment]
    page_count: int | None


def _decode_text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---------------- PDF ----------------

def parse_pdf(data: bytes) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # Many PDFs are "encrypted" with an empty user password (copy protection only).
            if not reader.decrypt(""):
                raise ParseError("PDF is password-protected")
        segments = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:  # a single corrupt page shouldn't fail the document
                text = ""
            segments.append(Segment(text=text, page=i))
    except PdfReadError as e:
        raise ParseError(f"Could not read PDF: {e}") from e
    if not any(s.text.strip() for s in segments):
        raise ParseError("No extractable text found. The PDF may be scanned images (OCR is not enabled).")
    return ParsedDocument(segments=segments, page_count=len(segments))


# ---------------- DOCX ----------------

def _paragraph_has_page_break(p_el) -> bool:
    for br in p_el.iter(qn("w:br")):
        if br.get(qn("w:type")) == "page":
            return True
    return any(True for _ in p_el.iter(qn("w:lastRenderedPageBreak")))


def _table_text(tbl) -> str:
    rows = []
    for row in tbl.rows:
        cells, seen = [], set()
        for c in row.cells:  # merged cells repeat; dedupe by identity
            if id(c._tc) in seen:
                continue
            seen.add(id(c._tc))
            cells.append(" ".join(c.text.split()))
        rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_docx(data: bytes) -> ParsedDocument:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as e:
        raise ParseError(f"Could not read Word document: {e}") from e

    page, section = 1, None
    segments: list[Segment] = []
    buf: list[str] = []

    def flush():
        text = "\n".join(buf).strip()
        if text:
            segments.append(Segment(text=text, page=page, section=section))
        buf.clear()

    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            para = docx.text.paragraph.Paragraph(child, document)
            if _paragraph_has_page_break(child):
                flush()
                page += 1
            style = (para.style.name or "").lower() if para.style is not None else ""
            text = para.text.strip()
            if not text:
                continue
            if style.startswith("heading") or style == "title":
                flush()
                section = text[:255]
                buf.append(text)
            else:
                buf.append(text)
        elif child.tag == qn("w:tbl"):
            buf.append(_table_text(docx.table.Table(child, document)))
    flush()
    if not segments:
        raise ParseError("Word document contains no text")
    return ParsedDocument(segments=segments, page_count=page)


# ---------------- TXT ----------------

def parse_txt(data: bytes) -> ParsedDocument:
    text = _decode_text(data)
    pages = text.split("\f")
    segments = [Segment(text=p, page=i) for i, p in enumerate(pages, start=1) if p.strip()]
    if not segments:
        raise ParseError("Text file is empty")
    return ParsedDocument(segments=segments, page_count=len(pages) if len(pages) > 1 else 1)


# ---------------- CSV ----------------

CSV_ROWS_PER_SEGMENT = 25


def parse_csv(data: bytes) -> ParsedDocument:
    text = _decode_text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ParseError("CSV needs a header row and at least one data row")
    header = [h.strip() or f"column_{i+1}" for i, h in enumerate(rows[0])]
    segments = []
    for start in range(1, len(rows), CSV_ROWS_PER_SEGMENT):
        block = rows[start:start + CSV_ROWS_PER_SEGMENT]
        # Render each row as "Header: value; Header: value" so every row is self-describing
        # and still meaningful when it ends up in a chunk without the header line.
        lines = ["; ".join(f"{header[i] if i < len(header) else f'column_{i+1}'}: {v.strip()}"
                           for i, v in enumerate(r) if v.strip()) for r in block]
        first, last = start + 1, start + len(block)  # 1-based file row numbers (header is row 1)
        segments.append(Segment(text="\n".join(lines), page=None, section=f"Rows {first}-{last}"))
    return ParsedDocument(segments=segments, page_count=None)


PARSERS = {".pdf": parse_pdf, ".docx": parse_docx, ".txt": parse_txt, ".csv": parse_csv}


def parse_file(extension: str, data: bytes) -> ParsedDocument:
    try:
        return PARSERS[extension](data)
    except KeyError:
        raise ParseError(f"No parser for {extension}") from None
