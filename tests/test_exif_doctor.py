"""Tests for exif_doctor. Fixtures are synthetic files built in code,
so no real photos (and no real personal metadata) are ever needed."""

import json
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import exif_doctor as ed


def jpeg_segment(marker, payload):
    return b"\xff" + bytes([marker]) + struct.pack(">H", len(payload) + 2) + payload


def tiff_bytes(gps):
    # Header: II, 42, IFD0 at offset 8.
    header = b"II" + struct.pack("<H", 42) + struct.pack("<I", 8)
    if gps:
        # One IFD0 entry: tag 0x8825 (GPS IFD), type LONG, count 1,
        # value = offset 26 where an empty GPS IFD lives.
        ifd = struct.pack("<H", 1)
        ifd += struct.pack("<HHI", 0x8825, 4, 1) + struct.pack("<I", 26)
        ifd += struct.pack("<I", 0)
        gps_ifd = struct.pack("<H", 0) + struct.pack("<I", 0)
        return header + ifd + gps_ifd
    ifd = struct.pack("<H", 0) + struct.pack("<I", 0)
    return header + ifd


def make_jpeg(gps=True, comment=True, app2=False):
    out = bytearray(b"\xff\xd8")
    out += jpeg_segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    out += jpeg_segment(0xE1, b"Exif\x00\x00" + tiff_bytes(gps))
    if app2:
        out += jpeg_segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + b"\x00" * 8)
    if comment:
        out += jpeg_segment(0xFE, b"my camera was here")
    out += jpeg_segment(0xDB, b"\x00" * 16)  # DQT
    out += jpeg_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")  # SOS header
    out += b"\x11\x22\x33"  # fake scan data
    out += b"\xff\xd9"  # EOI
    return bytes(out)


def png_chunk(ctype, payload):
    raw = ctype.encode("latin-1") + payload
    return struct.pack(">I", len(payload)) + raw + struct.pack(">I", zlib.crc32(raw) & 0xFFFFFFFF)


def make_png(gps=True, iccp=False):
    out = bytearray(b"\x89PNG\r\n\x1a\n")
    out += png_chunk("IHDR", b"\x00" * 13)
    out += png_chunk("tEXt", b"Author\x00Jane Example")
    out += png_chunk("eXIf", tiff_bytes(gps))
    if iccp:
        out += png_chunk("iCCP", b"icc\x00\x00" + b"\x00" * 4)
    out += png_chunk("IDAT", b"\x78\x9c\x01\x02")
    out += png_chunk("IEND", b"")
    return bytes(out)


def webp_chunk(fourcc, payload):
    pad = b"\x00" if len(payload) % 2 else b""
    return fourcc.encode("latin-1") + struct.pack("<I", len(payload)) + payload + pad


def make_webp():
    body = b"WEBP"
    body += webp_chunk("VP8X", b"\x00" * 10)
    body += webp_chunk("EXIF", b"II" + struct.pack("<H", 42) + struct.pack("<I", 8) + b"\x00" * 6)
    body += webp_chunk("XMP ", b"<x:xmpmeta/>")
    body += webp_chunk("VP8L", b"\x2f\x01\x02")
    return b"RIFF" + struct.pack("<I", len(body)) + body


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


# JPEG


def test_jpeg_gps_exif_detected():
    fmt, findings = ed.scan_bytes(make_jpeg(gps=True), "exif")
    assert fmt == "jpeg"
    assert "APP1 Exif (GPS present)" in findings
    assert "COM comment" in findings


def test_jpeg_no_gps_label():
    _fmt, findings = ed.scan_bytes(make_jpeg(gps=False, comment=False), "exif")
    assert findings == ["APP1 Exif"]


def test_jpeg_strip_keeps_image_segments():
    fmt, cleaned, removed, leftover = ed.strip_bytes(make_jpeg(), "exif")
    assert fmt == "jpeg"
    assert removed == ["APP1 Exif (GPS present)", "COM comment"]
    assert leftover == []
    assert b"JFIF" in cleaned
    assert b"\x11\x22\x33" in cleaned  # scan data survived
    assert b"my camera was here" not in cleaned
    _fmt2, findings2 = ed.scan_bytes(cleaned, "exif")
    assert findings2 == []


def test_jpeg_all_mode_strips_app2_exif_mode_keeps():
    data = make_jpeg(comment=False, app2=True)
    _f, _c, removed_exif, _l = ed.strip_bytes(data, "exif")
    assert removed_exif == ["APP1 Exif (GPS present)"]
    _f, cleaned, removed_all, _l = ed.strip_bytes(data, "all")
    assert "APP2" in removed_all
    assert b"ICC_PROFILE" not in cleaned


def test_jpeg_strip_is_idempotent():
    _f, cleaned, _r, _l = ed.strip_bytes(make_jpeg(), "exif")
    _f, cleaned2, removed2, _l = ed.strip_bytes(cleaned, "exif")
    assert cleaned2 == cleaned
    assert removed2 == []


def test_jpeg_truncated_raises():
    with pytest.raises(ValueError):
        ed.strip_bytes(b"\xff\xd8\xff\xe1\x00", "exif")


# PNG


def test_png_text_and_exif_detected():
    fmt, findings = ed.scan_bytes(make_png(), "exif")
    assert fmt == "png"
    assert "tEXt" in findings
    assert "eXIf (GPS present)" in findings


def test_png_strip_keeps_image_data():
    _f, cleaned, removed, leftover = ed.strip_bytes(make_png(), "exif")
    assert leftover == []
    assert b"Jane Example" not in cleaned
    assert b"IDAT" in cleaned and b"IHDR" in cleaned
    # Chunks still well formed: re-walking must succeed.
    assert [c[0] for c in ed._walk_png(cleaned)] == ["IHDR", "IDAT", "IEND"]


def test_png_all_mode_strips_iccp():
    data = make_png(iccp=True)
    _f, _c, removed, _l = ed.strip_bytes(data, "all")
    assert "iCCP" in removed
    _f, _c, removed_exif, _l = ed.strip_bytes(data, "exif")
    assert "iCCP" not in removed_exif


# WebP


def test_webp_exif_and_xmp_detected():
    fmt, findings = ed.scan_bytes(make_webp(), "exif")
    assert fmt == "webp"
    assert findings == ["EXIF", "XMP"]


def test_webp_strip_fixes_riff_size():
    _f, cleaned, removed, leftover = ed.strip_bytes(make_webp(), "exif")
    assert removed == ["EXIF", "XMP"]
    assert leftover == []
    assert b"VP8X" in cleaned and b"VP8L" in cleaned
    assert struct.unpack_from("<I", cleaned, 4)[0] == len(cleaned) - 8


# CLI behaviour


def test_check_clean_and_dirty(tmp_path):
    clean = write(tmp_path, "clean.jpg", make_jpeg(gps=False, comment=False))
    # A no-GPS Exif file is still dirty (Exif present), so build a truly
    # clean JPEG: SOI + APP0 + DQT + SOS + scan + EOI.
    bare = b"\xff\xd8" + jpeg_segment(0xE0, b"JFIF\x00") + jpeg_segment(0xDB, b"\x00" * 4)
    bare += jpeg_segment(0xDA, b"\x01\x00") + b"\x11\x22" + b"\xff\xd9"
    clean = write(tmp_path, "clean.jpg", bare)
    dirty = write(tmp_path, "dirty.jpg", make_jpeg())
    assert ed.main([clean, "--check"]) == 0
    assert ed.main([dirty, "--check"]) == 1


def test_dry_run_writes_nothing(tmp_path):
    dirty = write(tmp_path, "d.jpg", make_jpeg())
    assert ed.main([dirty, "--dry-run"]) == 0
    assert list(tmp_path.iterdir()) == [Path(dirty)]


def test_default_output_and_rescan(tmp_path):
    dirty = write(tmp_path, "photo.jpg", make_jpeg())
    assert ed.main([dirty]) == 0
    cleaned = tmp_path / "photo.clean.jpg"
    assert cleaned.exists()
    _fmt, findings = ed.scan_bytes(cleaned.read_bytes(), "exif")
    assert findings == []


def test_in_place(tmp_path):
    dirty = write(tmp_path, "p.jpg", make_jpeg())
    assert ed.main([dirty, "--in-place"]) == 0
    _fmt, findings = ed.scan_bytes(Path(dirty).read_bytes(), "exif")
    assert findings == []


def test_dir_batch_and_out_dir(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.jpg").write_bytes(make_jpeg())
    (src / "b.png").write_bytes(make_png())
    (src / "notes.txt").write_text("not an image")
    out = tmp_path / "out"
    assert ed.main(["--dir", str(src), "--out-dir", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["a.clean.jpg", "b.clean.png"]


def test_json_report(tmp_path, capsys):
    dirty = write(tmp_path, "d.jpg", make_jpeg())
    assert ed.main([dirty, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report[0]["format"] == "jpeg"
    assert "APP1 Exif (GPS present)" in report[0]["removed"]


def test_unsupported_and_missing_inputs(tmp_path):
    junk = write(tmp_path, "x.txt", b"hello world, not an image")
    assert ed.main([junk]) == 2
    assert ed.main([]) == 2


def test_report_file_written(tmp_path):
    dirty = write(tmp_path, "d.png", make_png())
    report_path = tmp_path / "report.json"
    assert ed.main([dirty, "--report", str(report_path)]) == 0
    report = json.loads(report_path.read_text())
    assert report[0]["format"] == "png"
    assert report[0]["output"].endswith("d.clean.png")
