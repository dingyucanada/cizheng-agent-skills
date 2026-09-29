# Report webfonts

These local WOFF2 fonts are renamed report subsets of Adobe's official Source
Han Serif SC Medium 2.003 and Source Han Sans SC Regular 2.005. They contain the
literal Unicode characters from `report.html`, all `report-assets/*.svg` text,
deployment status text, ASCII, and a small set of common Chinese UI words.
They are not general-purpose Chinese fonts: rebuild when report text changes.

The derived families are **Cizheng Report Serif** and **Cizheng Report Sans**.
The reserved upstream font name `Source` is retained only in original
attribution and license records; derived family and PostScript names are
changed. Outlines, metrics, embedded original copyright and OFL records remain.
`FONT-SOURCES.json` pins the exact official repository commits, download URLs,
original file SHA-256 values, input SHA-256 values, and generated font SHA-256
values. Both unmodified upstream license files are distributed alongside the
fonts. The original font metadata and repository license text have different
copyright year ranges; both are retained verbatim, not reconciled by editing.

Load `report-assets/fonts/report-fonts.css` **after** `report.css` in the HTML.
The sheet overrides the separate print-only system font on chapter headings.
Font files are served from the same site; no external font service is used.
The 400-weight sans and 500-weight serif are static fonts; browsers may synthesize
other requested bold weights. External SVG images keep their own internal font
rules; their text is included in the subset for future inline use but a page
stylesheet does not change the typography inside an `<img>` SVG.

For PDF export, wait for `document.fonts.ready` and all images before printing.
Text extraction must be checked directly against the report headings. This
package does not normalize text or replace incorrectly extracted characters.

## Rebuild

Create a private environment and install `requirements.txt`, then run:

```text
python build_report_fonts.py --site /path/to/site --upstream-dir /private/cache/of/pinned/font/inputs --download
```

Without `--download`, all input fonts and license files must already exist in
`--upstream-dir`. Downloads are checked against the pinned SHA-256 values before
use. The script writes only to `--output` (this folder by default) and the
requested upstream cache; it never edits report HTML, SVG, CSS, or PDF files.

Use the same pinned fontTools and Brotli versions for reproducibility. The
generator checks literal Unicode coverage, preserves copyright records, and
fixes timestamps to the original font values.
