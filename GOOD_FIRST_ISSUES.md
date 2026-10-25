# Good first issues

Seeded ideas for new contributors. Each one is small, tested, and safe
to take: open an issue or a pull request against this file's text.

## 1. Add AVIF container support

Problem: AVIF files use the ISO-BMFF box structure, so exif-doctor
reports them as unsupported. Work: detect the `ftyp` box with an `avif`
brand, walk boxes, and drop `Exif` (and `xml ` XMP) boxes inside the
`meta` box, repairing box sizes. Keep image boxes untouched.
Files: exif_doctor.py (new format entry), tests/test_exif_doctor.py,
README.md (formats table). Tests to add: AVIF Exif box detected and
removed, image boxes preserved, malformed box errors cleanly.

## 2. Report the actual GPS coordinates in --json

Problem: the report says "GPS present" but never shows what was found,
so a user cannot tell whether the coordinates point at their home.
Work: decode the GPS IFD rationals (latitude, longitude, refs) and add
`gps: {"latitude": ..., "longitude": ...}` to the JSON report only
(never to the plain text output, to avoid leaking coordinates into
logs). Files: exif_doctor.py (`_has_gps_tiff` becomes a parser),
tests/test_exif_doctor.py, README.md. Tests to add: known GPS IFD
decodes to the right coordinates, missing GPS IFD yields no gps key.

## 3. Add a --keep-orientation option

Problem: stripping every APP1 segment also removes the Orientation
tag, so a cleaned photo may display rotated in some viewers. Work:
add `--keep-orientation`, which rebuilds the APP1 Exif segment with
only the Orientation tag (and the TIFF header) instead of dropping it
whole. Files: exif_doctor.py, tests/test_exif_doctor.py, README.md.
Tests to add: orientation preserved with the flag, fully stripped
without it, output rescans with only an Orientation finding.

## 4. Add a --diff report showing bytes saved

Problem: users cannot see how much metadata a file carried. Work: add
a `--diff` flag that prints, per file, the input size, output size and
bytes removed, plus a total line. Files: exif_doctor.py (report dict
gains `size_before`/`size_after`), tests/test_exif_doctor.py,
README.md. Tests to add: sizes match the real files, dry-run still
reports sizes without writing, JSON output includes the new fields.
