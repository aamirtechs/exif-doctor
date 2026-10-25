#!/usr/bin/env python3
"""exif-doctor: strip EXIF, GPS and other metadata from JPEG, PNG and WebP files.

Zero dependencies, Python 3.9+. The tool never modifies the input file
unless --in-place is given; by default cleaned copies are written next to
the inputs with a ".clean" suffix (or into --out-dir).

Metadata handled:
  JPEG: APP1 Exif (including the GPS IFD, reported separately), APP1 XMP,
        APP13 Photoshop IRB, COM comments. --mode all also strips every
        other APPn segment except APP0 (JFIF).
  PNG:  tEXt, zTXt, iTXt, eXIf (including GPS). --mode all also strips
        iCCP and tIME.
  WebP: EXIF and XMP chunks inside the RIFF container.

A rescan of every cleaned file is part of the pipeline: if anything
survives, the file is reported as still dirty instead of silently kept.
"""

import argparse
import json
import os
import struct
import sys

VERSION = "1.0.0"

JPEG_SOI = b"\xff\xd8"
PNG_SIG = b"\x89PNG\r\n\x1a\n"

# (marker, label) for JPEG segments that carry metadata in exif mode.
JPEG_EXIF_MODE = {
    0xE1: "APP1",
    0xED: "APP13",
    0xFE: "COM",
}

PNG_EXIF_MODE = {"tEXt", "zTXt", "iTXt", "eXIf"}
PNG_ALL_MODE_EXTRA = {"iCCP", "tIME"}


def _u16be(buf, off):
    return struct.unpack_from(">H", buf, off)[0]


def _u32be(buf, off):
    return struct.unpack_from(">I", buf, off)[0]


def _u32le(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def _has_gps_tiff(tiff):
    """Best-effort check for a GPS IFD (tag 0x8825) in TIFF data.

    Returns True only when the TIFF header parses and an IFD0 entry
    points at a GPS IFD. Unparseable data returns False; the caller
    still reports the surrounding Exif segment itself.
    """
    try:
        if tiff[:2] == b"II":
            endian = "<"
        elif tiff[:2] == b"MM":
            endian = ">"
        else:
            return False
        if struct.unpack_from(endian + "H", tiff, 2)[0] != 42:
            return False
        ifd_off = struct.unpack_from(endian + "I", tiff, 4)[0]
        count = struct.unpack_from(endian + "H", tiff, ifd_off)[0]
        for i in range(count):
            entry = ifd_off + 2 + i * 12
            tag = struct.unpack_from(endian + "H", tiff, entry)[0]
            if tag == 0x8825:
                return True
        return False
    except (struct.error, IndexError):
        return False


def _jpeg_exif_label(data):
    """Label an APP1 segment: Exif, XMP, or plain APP1."""
    if data.startswith(b"Exif\x00\x00"):
        tiff = data[6:]
        if _has_gps_tiff(tiff):
            return "APP1 Exif (GPS present)"
        return "APP1 Exif"
    if b"http://ns.adobe.com/xap/1.0/" in data[:200] or data.startswith(
        b"http://ns.adobe.com/xap/1.0/"
    ):
        return "APP1 XMP"
    return "APP1"


def _walk_jpeg(data):
    """Yield (marker, start, end, payload) for each JPEG segment.

    The SOS segment is yielded with end at the end of its header; the
    caller must treat everything after it as scan data. Raises ValueError
    on malformed input.
    """
    if not data.startswith(JPEG_SOI):
        raise ValueError("not a JPEG file (missing SOI marker)")
    segments = []
    pos = 2
    while pos < len(data):
        if data[pos] != 0xFF:
            raise ValueError("malformed JPEG: expected marker at offset %d" % pos)
        # Skip fill bytes.
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            break
        marker = data[pos]
        pos += 1
        if marker == 0xD9:  # EOI
            segments.append((marker, pos - 2, pos, b""))
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            segments.append((marker, pos - 2, pos, b""))
            continue
        if pos + 2 > len(data):
            raise ValueError("truncated JPEG segment header")
        length = _u16be(data, pos)
        if length < 2 or pos + length > len(data):
            raise ValueError("truncated JPEG segment")
        payload = data[pos + 2 : pos + length]
        segments.append((marker, pos - 2, pos + length, payload))
        pos += length
        if marker == 0xDA:  # SOS: scan data follows verbatim
            break
    return segments


def scan_jpeg(data, mode="exif"):
    """Return a list of finding labels for a JPEG byte string."""
    findings = []
    try:
        segments = _walk_jpeg(data)
    except ValueError as exc:
        return ["unparseable JPEG: %s" % exc]
    for marker, _start, _end, payload in segments:
        if marker == 0xE1:
            findings.append(_jpeg_exif_label(payload))
        elif marker == 0xED:
            findings.append("APP13 Photoshop")
        elif marker == 0xFE:
            findings.append("COM comment")
        elif mode == "all" and 0xE0 <= marker <= 0xEF and marker != 0xE0:
            findings.append("APP%d" % (marker - 0xE0))
    return findings


def strip_jpeg(data, mode="exif"):
    """Return (cleaned_bytes, removed_labels) for a JPEG byte string."""
    segments = _walk_jpeg(data)
    out = bytearray(JPEG_SOI)
    removed = []
    scan_data = None
    for marker, start, end, payload in segments:
        if marker == 0xDA:
            # SOS header kept, scan data copied verbatim.
            out += data[start:end]
            scan_data = data[end:]
            break
        drop = False
        label = None
        if marker == 0xE1:
            label = _jpeg_exif_label(payload)
            drop = True
        elif marker == 0xED:
            label = "APP13 Photoshop"
            drop = True
        elif marker == 0xFE:
            label = "COM comment"
            drop = True
        elif mode == "all" and 0xE0 <= marker <= 0xEF and marker != 0xE0:
            label = "APP%d" % (marker - 0xE0)
            drop = True
        if drop:
            removed.append(label)
        else:
            out += data[start:end]
    if scan_data is not None:
        out += scan_data
    else:
        # No SOS seen: copy any trailing bytes (e.g. EOI) already handled
        # by the segment loop, nothing extra to append.
        pass
    return bytes(out), removed


def _walk_png(data):
    """Yield (type, start, end, payload) for each PNG chunk."""
    if not data.startswith(PNG_SIG):
        raise ValueError("not a PNG file (missing signature)")
    chunks = []
    pos = 8
    while pos + 8 <= len(data):
        length = _u32be(data, pos)
        ctype = data[pos + 4 : pos + 8].decode("latin-1")
        end = pos + 8 + length + 4
        if end > len(data):
            raise ValueError("truncated PNG chunk %s" % ctype)
        chunks.append((ctype, pos, end, data[pos + 8 : pos + 8 + length]))
        pos = end
        if ctype == "IEND":
            break
    return chunks


def _png_chunk_label(ctype, payload):
    if ctype == "eXIf":
        if _has_gps_tiff(payload):
            return "eXIf (GPS present)"
        return "eXIf"
    return ctype


def scan_png(data, mode="exif"):
    try:
        chunks = _walk_png(data)
    except ValueError as exc:
        return ["unparseable PNG: %s" % exc]
    drop = set(PNG_EXIF_MODE)
    if mode == "all":
        drop |= PNG_ALL_MODE_EXTRA
    return [_png_chunk_label(t, p) for t, _s, _e, p in chunks if t in drop]


def strip_png(data, mode="exif"):
    chunks = _walk_png(data)
    drop = set(PNG_EXIF_MODE)
    if mode == "all":
        drop |= PNG_ALL_MODE_EXTRA
    out = bytearray(PNG_SIG)
    removed = []
    for ctype, start, end, payload in chunks:
        if ctype in drop:
            removed.append(_png_chunk_label(ctype, payload))
        else:
            out += data[start:end]
    return bytes(out), removed


def _walk_webp(data):
    """Yield (fourcc, start, end, payload) for each WebP chunk."""
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ValueError("not a WebP file (missing RIFF/WEBP header)")
    chunks = []
    pos = 12
    while pos + 8 <= len(data):
        fourcc = data[pos : pos + 4].decode("latin-1")
        size = _u32le(data, pos + 4)
        end = pos + 8 + size + (size % 2)
        if end > len(data):
            raise ValueError("truncated WebP chunk %s" % fourcc)
        chunks.append((fourcc, pos, end, data[pos + 8 : pos + 8 + size]))
        pos = end
    return chunks


def scan_webp(data, mode="exif"):
    try:
        chunks = _walk_webp(data)
    except ValueError as exc:
        return ["unparseable WebP: %s" % exc]
    return [t.strip() for t, _s, _e, _p in chunks if t in ("EXIF", "XMP ")]


def strip_webp(data, mode="exif"):
    chunks = _walk_webp(data)
    out = bytearray(b"RIFF\x00\x00\x00\x00WEBP")
    removed = []
    for fourcc, start, end, _payload in chunks:
        if fourcc in ("EXIF", "XMP "):
            removed.append(fourcc.strip())
        else:
            out += data[start:end]
    riff_size = len(out) - 8
    struct.pack_into("<I", out, 4, riff_size)
    return bytes(out), removed


FORMATS = {
    "jpeg": (scan_jpeg, strip_jpeg),
    "png": (scan_png, strip_png),
    "webp": (scan_webp, strip_webp),
}


def detect_format(data):
    if data.startswith(JPEG_SOI):
        return "jpeg"
    if data.startswith(PNG_SIG):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def scan_bytes(data, mode="exif"):
    fmt = detect_format(data)
    if fmt is None:
        return None, ["unsupported or unrecognized file (expected JPEG, PNG or WebP)"]
    scan, _strip = FORMATS[fmt]
    return fmt, scan(data, mode)


def strip_bytes(data, mode="exif"):
    fmt = detect_format(data)
    if fmt is None:
        raise ValueError("unsupported or unrecognized file (expected JPEG, PNG or WebP)")
    _scan, strip = FORMATS[fmt]
    cleaned, removed = strip(data, mode)
    # Rescan: a clean result must report zero findings.
    _fmt2, leftover = scan_bytes(cleaned, mode)
    return fmt, cleaned, removed, leftover


def output_path(path, suffix, out_dir, in_place):
    if in_place:
        return path
    base = os.path.basename(path)
    stem, ext = os.path.splitext(base)
    name = stem + suffix + ext
    if out_dir:
        return os.path.join(out_dir, name)
    return os.path.join(os.path.dirname(path), name)


def collect_inputs(paths, directory):
    found = list(paths)
    if directory:
        for root, _dirs, files in os.walk(directory):
            for name in sorted(files):
                if name.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
                    found.append(os.path.join(root, name))
    return found


def process(path, args):
    """Process one file. Returns (report_dict, exit_code)."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        return {"file": path, "error": str(exc)}, 2
    fmt, findings = scan_bytes(data, args.mode)
    if fmt is None:
        return {"file": path, "error": findings[0]}, 2
    report = {
        "file": path,
        "format": fmt,
        "findings": findings,
        "removed": [],
        "output": None,
        "still_dirty": [],
    }
    if args.check:
        return report, 0
    if not findings:
        return report, 0
    if args.dry_run:
        report["output"] = output_path(path, args.suffix, args.out_dir, args.in_place)
        return report, 0
    try:
        _fmt, cleaned, removed, leftover = strip_bytes(data, args.mode)
    except ValueError as exc:
        return {"file": path, "error": str(exc)}, 2
    report["removed"] = removed
    report["still_dirty"] = leftover
    if leftover:
        return report, 2
    out_path = output_path(path, args.suffix, args.out_dir, args.in_place)
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
    try:
        with open(out_path, "wb") as handle:
            handle.write(cleaned)
    except OSError as exc:
        return {"file": path, "error": str(exc)}, 2
    report["output"] = out_path
    return report, 0


def build_parser():
    parser = argparse.ArgumentParser(
        prog="exif-doctor",
        description="Strip EXIF, GPS and other metadata from JPEG, PNG and WebP files.",
    )
    parser.add_argument("paths", nargs="*", help="image files to clean")
    parser.add_argument("--dir", dest="directory", help="recursively clean an image folder")
    parser.add_argument("--out-dir", help="write cleaned copies into this directory")
    parser.add_argument("--suffix", default=".clean", help="suffix for cleaned copies (default: .clean)")
    parser.add_argument("--in-place", action="store_true", help="overwrite the input files")
    parser.add_argument("--mode", choices=["exif", "all"], default="exif",
                        help="exif: Exif/GPS/XMP/comments only; all: also strip every APPn chunk, iCCP and tIME")
    parser.add_argument("--check", action="store_true",
                        help="report metadata without writing anything; exit 1 if any file has metadata")
    parser.add_argument("--dry-run", action="store_true", help="show what would be removed, write nothing")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    parser.add_argument("--report", help="write the full report as JSON to this path")
    parser.add_argument("--version", action="version", version="exif-doctor " + VERSION)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    inputs = collect_inputs(args.paths, args.directory)
    if not inputs:
        print("exif-doctor: no input files (pass file paths or --dir)", file=sys.stderr)
        return 2
    reports = []
    exit_code = 0
    for path in inputs:
        report, code = process(path, args)
        reports.append(report)
        if code != 0:
            exit_code = code if code == 2 else max(exit_code, code)
        if args.check and report.get("findings"):
            exit_code = max(exit_code, 1)
    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for report in reports:
            if "error" in report:
                print("%s: error: %s" % (report["file"], report["error"]))
                continue
            if args.check:
                if report["findings"]:
                    print("%s: %s [metadata found]" % (report["file"], ", ".join(report["findings"])))
                else:
                    print("%s: clean" % report["file"])
            elif not report["findings"]:
                print("%s: clean, nothing to strip" % report["file"])
            elif args.dry_run:
                print("%s -> %s [would remove %s]" % (
                    report["file"], report["output"], ", ".join(report["findings"])))
            else:
                print("%s -> %s [removed %s]" % (
                    report["file"], report["output"], ", ".join(report["removed"])))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(reports, handle, indent=2)
    total_removed = sum(len(r.get("removed", [])) for r in reports)
    dirty = sum(1 for r in reports if r.get("findings"))
    if not args.json:
        print("done: %d file(s), %d with metadata, %d chunk(s) removed" % (
            len(reports), dirty, total_removed))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
