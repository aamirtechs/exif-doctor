#!/usr/bin/env python3
"""Generate small synthetic sample images with fake metadata.

The samples contain no real photos and no real personal data: they are
minimal JPEG/PNG/WebP structures built in code so the README examples
and the --check demo run anywhere. Run from the project root:

    python3 examples/make_samples.py
    python3 exif_doctor.py --check examples/
"""

import struct
import zlib
from pathlib import Path


def jpeg_segment(marker, payload):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


def tiff_with_gps():
    header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
    ifd = struct.pack("<H", 1)
    ifd += struct.pack("<HHI", 0x8825, 4, 1) + struct.pack("<I", 26)
    ifd += struct.pack("<I", 0)
    gps_ifd = struct.pack("<H", 0) + struct.pack("<I", 0)
    return header + ifd + gps_ifd


def make_jpeg():
    out = bytearray(b"\xff\xd8")
    out += jpeg_segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    out += jpeg_segment(0xE1, b"Exif\x00\x00" + tiff_with_gps())
    out += jpeg_segment(0xFE, b"sample comment")
    out += jpeg_segment(0xDB, b"\x00" * 16)
    out += jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    out += b"\x11\x22\x33" + b"\xff\xd9"
    return bytes(out)


def png_chunk(ctype, payload):
    raw = ctype.encode("latin-1") + payload
    return struct.pack(">I", len(payload)) + raw + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)


def make_png():
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += png_chunk("IHDR", b"\x00" * 13)
    out += png_chunk("tEXt", b"Author\x00Sample Author")
    out += png_chunk("eXIf", tiff_with_gps())
    out += png_chunk("IDAT", b"\x78\x9c\x01\x02")
    out += png_chunk("IEND", b"")
    return bytes(out)


def webp_chunk(fourcc, payload):
    pad = b"\x00" if len(payload) % 2 else b""
    return fourcc.encode("latin-1") + struct.pack("<I", len(payload)) + payload + pad


def make_webp():
    body = b"WEBP"
    body += webp_chunk("VP8X", b"\x00" * 10)
    body += webp_chunk("EXIF", tiff_with_gps())
    body += webp_chunk("VP8L", b"\x2f\x01\x02")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def main():
    here = Path(__file__).resolve().parent
    (here / "sample.jpg").write_bytes(make_jpeg())
    (here / "sample.png").write_bytes(make_png())
    (here / "sample.webp").write_bytes(make_webp())
    print("wrote sample.jpg, sample.png, sample.webp")


if __name__ == "__main__":
    main()
