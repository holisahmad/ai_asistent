"""Parser interface + implementasi per format (Fase 4).

Setiap parser menghasilkan daftar `Section` — potongan teks dengan
locator (page/slide/sheet/row/char) yang menjadi sitasi sumber.
Interface sengaja kecil agar parser eksternal (OCR/transkripsi via
provider adapter) dapat ditambahkan tanpa mengubah pemanggil.
"""

import csv
import io
from dataclasses import dataclass
from typing import Protocol

from ai_asistent_core.config import get_settings


@dataclass(frozen=True)
class Section:
    """Potongan hasil ekstraksi dengan locator sumber."""

    text: str
    locator_type: str  # page | slide | sheet | row | char
    locator_start: int
    locator_end: int


@dataclass(frozen=True)
class ParsedDocument:
    """Hasil parsing satu file."""

    source_format: str  # pdf|docx|pptx|xlsx|txt|md|csv
    title: str | None
    sections: list[Section]
    meta: dict[str, str]


class Parser(Protocol):
    """Kontrak parser: bytes → ParsedDocument."""

    def parse(self, data: bytes) -> ParsedDocument: ...


def _blank_guard(sections: list[Section]) -> list[Section]:
    return [s for s in sections if s.text.strip()]


class PdfParser:
    """Parser PDF per halaman via pypdf."""

    def parse(self, data: bytes) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        sections: list[Section] = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                sections.append(
                    Section(text=text, locator_type="page", locator_start=i, locator_end=i)
                )
        title = None
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title)
        return ParsedDocument(
            source_format="pdf", title=title, sections=_blank_guard(sections),
            meta={"pages": str(len(reader.pages))},
        )


class DocxParser:
    """Parser DOCX: heading → page-ish break; paragraf per locator `page`虚拟."""

    def parse(self, data: bytes) -> ParsedDocument:
        import docx

        doc = docx.Document(io.BytesIO(data))
        sections: list[Section] = []
        buf: list[str] = []
        page = 1

        def flush() -> None:
            nonlocal buf
            text = "\n".join(buf).strip()
            if text:
                sections.append(
                    Section(text=text, locator_type="page", locator_start=page, locator_end=page)
                )
            buf = []

        for para in doc.paragraphs:
            style_name = para.style.name if para.style is not None else ""
            style = style_name.lower()
            if "heading" in style and buf:
                flush()
                page += 1
            if para.text.strip():
                buf.append(para.text)
        flush()

        for table in doc.tables:
            rows = ["\t".join(c.text.strip() for c in row.cells) for row in table.rows]
            text = "\n".join(r for r in rows if r.strip())
            if text:
                sections.append(
                    Section(text=text, locator_type="page", locator_start=page, locator_end=page)
                )
        return ParsedDocument(
            source_format="docx",
            title=doc.core_properties.title or None,
            sections=_blank_guard(sections),
            meta={"paragraphs": str(len(doc.paragraphs))},
        )


class PptxParser:
    """Parser PPTX per slide."""

    def parse(self, data: bytes) -> ParsedDocument:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
        sections: list[Section] = []
        for i, slide in enumerate(prs.slides, start=1):
            texts = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    t = shape.text_frame.text.strip()
                    if t:
                        texts.append(t)
            if texts:
                sections.append(
                    Section(
                        text="\n".join(texts),
                        locator_type="slide",
                        locator_start=i,
                        locator_end=i,
                    )
                )
        return ParsedDocument(
            source_format="pptx", title=None, sections=_blank_guard(sections),
            meta={"slides": str(len(prs.slides))},
        )


class XlsxParser:
    """Parser XLSX per sheet (openpyxl, read-only)."""

    def parse(self, data: bytes) -> ParsedDocument:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        sections: list[Section] = []
        for ws in wb.worksheets:
            lines: list[str] = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if v is None else str(v) for v in row]
                if any(c.strip() for c in cells):
                    lines.append("\t".join(cells))
            if lines:
                sheet_no = wb.sheetnames.index(ws.title) + 1
                sections.append(
                    Section(
                        text="\n".join(lines),
                        locator_type="sheet",
                        locator_start=sheet_no,
                        locator_end=sheet_no,
                    )
                )
        return ParsedDocument(
            source_format="xlsx", title=None, sections=_blank_guard(sections),
            meta={"sheets": str(len(wb.sheetnames))},
        )


class TextLikeParser:
    """Parser TXT/MD: satu section per `page` virtual 4000 karakter."""

    def __init__(self, fmt: str) -> None:
        self._fmt = fmt

    def parse(self, data: bytes) -> ParsedDocument:
        text = data.decode("utf-8", errors="replace")
        page_size = 4000
        sections: list[Section] = []
        for _i, offset in enumerate(range(0, len(text), page_size), start=1):
            chunk = text[offset : offset + page_size]
            if chunk.strip():
                sections.append(
                    Section(
                        text=chunk,
                        locator_type="char",
                        locator_start=offset,
                        locator_end=offset + len(chunk),
                    )
                )
        title = None
        if self._fmt == "md":
            for line in text.splitlines():
                if line.strip().startswith("# "):
                    title = line.lstrip("# ").strip()[:500]
                    break
        return ParsedDocument(
            source_format=self._fmt, title=title, sections=_blank_guard(sections), meta={}
        )


class CsvParser:
    """Parser CSV: section per blok baris (200 baris) dengan locator baris."""

    ROWS_PER_SECTION = 200

    def parse(self, data: bytes) -> ParsedDocument:
        text = data.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        sections: list[Section] = []
        buf: list[str] = []
        start_row = 1
        for i, row in enumerate(reader, start=1):
            buf.append("\t".join(row))
            if len(buf) >= self.ROWS_PER_SECTION:
                sections.append(
                    Section(
                        text="\n".join(buf),
                        locator_type="row",
                        locator_start=start_row,
                        locator_end=i,
                    )
                )
                buf = []
                start_row = i + 1
        if buf:
            sections.append(
                Section(
                    text="\n".join(buf),
                    locator_type="row",
                    locator_start=start_row,
                    locator_end=i,
                )
            )
        return ParsedDocument(
            source_format="csv", title=None, sections=_blank_guard(sections),
            meta={"total_rows": str(i)},
        )


PARSERS: dict[str, Parser] = {
    ".pdf": PdfParser(),
    ".docx": DocxParser(),
    ".pptx": PptxParser(),
    ".xlsx": XlsxParser(),
    ".txt": TextLikeParser("txt"),
    ".md": TextLikeParser("md"),
    ".csv": CsvParser(),
}

SUPPORTED_EXTENSIONS = set(PARSERS.keys())


def parse_file(filename: str, data: bytes) -> ParsedDocument:
    """Pilih parser dari ekstensi; raise ValueError bila tidak didukung."""
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    parser = PARSERS.get(ext)
    if parser is None:
        raise ValueError(f"No parser for extension {ext or '(none)'}")
    _ = get_settings()  # pastikan settings ter-inisialisasi (efek samping aman)
    return parser.parse(data)
