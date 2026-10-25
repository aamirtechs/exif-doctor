# exif-doctor

[![GitHub stars](https://img.shields.io/github/stars/aamirtechs/exif-doctor?style=social)](https://github.com/aamirtechs/exif-doctor/stargazers) [![GitHub forks](https://img.shields.io/github/forks/aamirtechs/exif-doctor?style=social)](https://github.com/aamirtechs/exif-doctor/network/members) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/aamirtechs/exif-doctor/blob/main/LICENSE) [![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/aamirtechs/exif-doctor/issues)

Strip EXIF, GPS and other metadata from JPEG, PNG and WebP files before
you share them, and prove the result is clean. Photos carry camera
serials, timestamps, and often exact GPS coordinates; most sharing flows
strip nothing. exif-doctor removes the metadata locally and rescans every
output, so a cleaned file that still contains metadata is reported
instead of silently kept.

Zero dependencies. Python 3.9+.

## Why

Before posting a photo, you want one answer: is anything personal still
inside it? exif-doctor gives that answer for a single file or a whole
folder, works offline, and never uploads anything. It also doubles as a
CI gate: `--check` exits nonzero when metadata is present, so a publish
pipeline can refuse to ship dirty images.

## Install

```bash
pip install exif-doctor
# or just run the single file, it has no dependencies:
python3 exif_doctor.py --help
```

## Quick example

Generate the synthetic samples (they contain fake metadata only, no real
photos), then check and clean them:

```bash
$ python3 examples/make_samples.py
wrote sample.jpg, sample.png, sample.webp

$ python3 exif_doctor.py --check examples/sample.jpg examples/sample.png examples/sample.webp
examples/sample.jpg: APP1 Exif (GPS present), COM comment [metadata found]
examples/sample.png: tEXt, eXIf (GPS present) [metadata found]
examples/sample.webp: EXIF [metadata found]
done: 3 file(s), 3 with metadata, 0 chunk(s) removed

$ python3 exif_doctor.py examples/sample.jpg examples/sample.png examples/sample.webp --out-dir cleaned/
examples/sample.jpg -> cleaned/sample.clean.jpg [removed APP1 Exif (GPS present), COM comment]
examples/sample.png -> cleaned/sample.clean.png [removed tEXt, eXIf (GPS present)]
examples/sample.webp -> cleaned/sample.clean.webp [removed EXIF]
done: 3 file(s), 3 with metadata, 5 chunk(s) removed

$ python3 exif_doctor.py --check cleaned/sample.clean.jpg cleaned/sample.clean.png cleaned/sample.clean.webp
cleaned/sample.clean.jpg: clean
cleaned/sample.clean.png: clean
cleaned/sample.clean.webp: clean
done: 3 file(s), 0 with metadata, 0 chunk(s) removed
```

(All outputs above are captured from real runs on the synthetic samples
in `examples/`.)

## What gets stripped

| Format | Default mode (`--mode exif`) | `--mode all` adds |
| --- | --- | --- |
| JPEG | APP1 Exif (GPS IFD reported separately), APP1 XMP, APP13 Photoshop, COM comments | every other APPn segment except APP0 (JFIF) |
| PNG | tEXt, zTXt, iTXt, eXIf (GPS reported separately) | iCCP, tIME |
| WebP | EXIF and XMP chunks | nothing extra |

Image data is never re-encoded: JPEG scan data, PNG IDAT chunks and
WebP VP8 chunks are copied verbatim, so cleaning cannot change how the
picture looks. JPEG APP0, PNG IHDR/IDAT/IEND and WebP VP8X/VP8L chunks
are always kept.

## Flags

| Flag | Meaning |
| --- | --- |
| `--dir DIR` | clean a folder recursively (jpg, jpeg, png, webp) |
| `--out-dir DIR` | write cleaned copies here instead of next to the inputs |
| `--suffix S` | suffix for cleaned copies (default: `.clean`) |
| `--in-place` | overwrite the input files |
| `--mode exif\|all` | how aggressive the strip is (default: exif) |
| `--check` | report only, exit 1 if any file has metadata |
| `--dry-run` | show what would be removed, write nothing |
| `--json` | print the full report as JSON |
| `--report PATH` | write the full report as JSON to a file |

## Limitations

- GPS detection reads the GPS IFD pointer (tag 0x8825) in the TIFF
  header; a malformed TIFF block is still reported as Exif, just
  without the GPS label.
- The tool strips container metadata only. It cannot remove a
  watermark burned into the pixels, or location clues visible in the
  picture itself.
- AVIF, HEIC and TIFF files are not supported yet (see the good first
  issues).

## Development

```bash
python3 -m pytest tests/ -q
```

## License

MIT. See LICENSE.
