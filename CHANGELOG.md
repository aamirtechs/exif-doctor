# Changelog

## v1.0.0 (2026-10-25)

- Initial release: strip EXIF, GPS, XMP, Photoshop IRB and comments from
  JPEG, PNG and WebP files, with a rescan proof on every output.
- JPEG: APP1 Exif (GPS IFD reported separately), APP1 XMP, APP13, COM;
  `--mode all` strips every other APPn segment except APP0.
- PNG: tEXt, zTXt, iTXt, eXIf; `--mode all` also strips iCCP and tIME.
- WebP: EXIF and XMP chunks, with the RIFF size repaired.
- `--check` CI gate, `--dry-run`, `--dir` batch mode, `--in-place`,
  `--out-dir`, `--json` and `--report` output.
- 19 tests, all passing.
