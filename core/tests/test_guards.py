"""Test unit Fase 9 — guard konten upload."""

from ai_asistent_core.guards import eicar_signature, scan_upload


def test_clean_markdown_and_pdf_pass() -> None:
    assert scan_upload("catatan.md", b"# Judul\n\nIsi dokumen normal.\n") is None
    assert scan_upload("laporan.pdf", b"%PDF-1.7\n...") is None
    assert scan_upload("data.csv", b"a,b\n1,2\n") is None


def test_empty_content_rejected() -> None:
    assert scan_upload("kosong.txt", b"") == "empty content"


def test_eicar_test_signature_rejected() -> None:
    payload = b"header\n" + eicar_signature() + b"\nfooter"
    reason = scan_upload("virus.txt", payload)
    assert reason is not None and "EICAR" in reason


def test_executable_magics_rejected() -> None:
    for name, magic in (
        ("setup.txt", b"MZ\x90\x00"),
        ("lib.bin", b"\x7fELF\x02\x01"),
        ("tool.md", b"\xcf\xfa\xed\xfe\x07"),
        ("script.md", b"#!/bin/sh\necho hai\n"),
    ):
        reason = scan_upload(name, magic + b"payload")
        assert reason is not None, name
        assert "biner" in reason


def test_binary_masquerading_as_text_rejected() -> None:
    reason = scan_upload("catatan.txt", b"teks biasa\x00\x01\x02biner")
    assert reason is not None and "NUL" in reason
    # Ekstensi non-teks tidak dikenai aturan NUL
    assert scan_upload("gambar.pdf", b"%PDF\x00binary") is None
