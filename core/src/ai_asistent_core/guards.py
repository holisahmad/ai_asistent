"""Penjaga konten upload (Fase 9) — pertahanan dasar sebelum parsing.

Bukan pengganti antivirus/ClamAV penuh, tapi menutup kasus paling umum:
executable yang disamarkan sebagai dokumen, file uji malware, dan biner
yang menyamar sebagai teks. Dipakai di API (upload) dan bisa dipakai
ulang worker (defense in depth).
"""

# Dirakit saat runtime agar tidak ada string signature utuh di repositori
# (menghindari file repo "terdeteksi" oleh antivirus pengembang).
_EICAR_PART_A = "X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
_EICAR_PART_B = "EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"

_EXECUTABLE_MAGICS: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "executable PE (MZ)"),
    (b"\x7fELF", "executable ELF"),
    (b"\xca\xfe\xba\xbe", "Mach-O/Java class magic"),
    (b"\xfe\xed\xfa\xce", "Mach-O 32-bit"),
    (b"\xfe\xed\xfa\xcf", "Mach-O 64-bit"),
    (b"\xcf\xfa\xed\xfe", "Mach-O 64-bit LE"),
    (b"\xce\xfa\xed\xfe", "Mach-O 32-bit LE"),
    (b"#!", "script shebang"),
)

_TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".html", ".json"}


def eicar_signature() -> bytes:
    """Signature file uji antivirus standar (dirakit runtime)."""
    return (_EICAR_PART_A + _EICAR_PART_B).encode("ascii")


def scan_upload(filename: str, data: bytes) -> str | None:
    """Kembalikan alasan penolakan, atau None bila konten dianggap aman.

    Pemeriksaan: signature malware uji, magic byte executable, dan biner
    ber-NUL pada ekstensi teks (indikasi file tidak sesuai ekstensi).
    """
    if not data:
        return "empty content"
    head = data[: 4 * 1024]
    if eicar_signature() in head or eicar_signature() in data[-2048:]:
        return "malware test signature terdeteksi (EICAR)"
    for magic, label in _EXECUTABLE_MAGICS:
        if head.startswith(magic):
            return f"konten biner tidak diizinkan: {label}"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext in _TEXT_EXTENSIONS and b"\x00" in data[: 64 * 1024]:
        return "file teks berisi byte NUL (kemungkinan biner tersamarkan)"
    return None
