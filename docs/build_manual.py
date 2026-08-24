#!/usr/bin/env python3
"""Build the Work Management user guide.

    bench/env/bin/python docs/build_manual.py

Writes docs/Work_Management_User_Guide.pdf and docs/Work_Management_Manual.docx
from the single content source in docs/manual_content.py. Two of the chapters
are generated from the code they document, so run this after changing the
approval stage catalogue or the Work Management Settings doctype.

Needs the bench environment's python: WeasyPrint renders the PDF and the
generated chapters import the app.
"""

import html
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "docs")]

import manual_content as content  # noqa: E402

PDF_OUT = ROOT / "docs" / "Work_Management_User_Guide.pdf"
DOCX_OUT = ROOT / "docs" / "Work_Management_Manual.docx"

INK = "#0a0a0a"
GOLD = "#a06000"
GREEN = "#1f6f4a"
MUTE = "#6f6d65"
RULE = "#e4e2dc"
WASH = "#faf9f6"


# ------------------------------------------------------------------ numbering


def numbered(blocks):
	"""Walk the content, attaching a number to every section and subsection.

	Numbers are computed once, here, so the table of contents and the headings
	can never disagree about them.
	"""
	out = []
	section = subsection = 0
	for kind, payload in blocks:
		if kind == "h2":
			section += 1
			subsection = 0
			out.append((kind, payload, str(section), f"s{section}"))
		elif kind == "h3":
			subsection += 1
			label = f"{section}.{subsection}"
			out.append((kind, payload, label, f"s{section}-{subsection}"))
		else:
			out.append((kind, payload, None, None))
	return out


# ----------------------------------------------------------------------- PDF

CSS = f"""
@page {{
  size: A4;
  margin: 20mm 18mm 18mm 18mm;
  @top-left {{
    content: "{content.TITLE} · {content.SUBTITLE}";
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 7.5pt; color: {MUTE}; letter-spacing: .06em; text-transform: uppercase;
    padding-bottom: 3mm;
  }}
  @bottom-right {{
    content: counter(page);
    font-family: "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 8.5pt; color: {MUTE}; padding-top: 4mm;
  }}
}}
@page cover {{ margin: 0; @top-left {{ content: none }} @bottom-right {{ content: none }} }}
@page frontmatter {{ @bottom-right {{ content: none }} }}

html {{ font-family: "Noto Serif", "DejaVu Serif", Georgia, serif;
        font-size: 10.2pt; line-height: 1.5; color: {INK}; }}
body {{ margin: 0; }}

h1, h2, h3, .part-title, .toc h2, th, .kicker, .cover-strap, .cover .sub {{
  font-family: "Noto Sans", "DejaVu Sans", sans-serif;
}}

/* ---- cover ---- */
.cover {{ page: cover; break-after: page; }}
.cover-band {{ background: {GREEN}; height: 96mm; padding: 34mm 20mm 0 20mm; color: #fff; }}
.cover-mark {{ margin-bottom: 6mm; }}
.cover-mark .bar {{ display: inline-block; width: 3.2mm; margin-right: 1.4mm;
                    background: rgba(255,255,255,.85); border-radius: .8mm;
                    vertical-align: bottom; }}
.cover h1 {{ font-size: 34pt; margin: 0 0 2mm 0; font-weight: 700; letter-spacing: -.5pt; }}
.cover .sub {{ font-size: 16pt; margin: 0; font-weight: 400; opacity: .92; }}
.cover-body {{ padding: 16mm 20mm 0 20mm; }}
.cover-strap {{ font-size: 11pt; line-height: 1.55; color: {INK}; max-width: 125mm;
                margin: 0 0 14mm 0; }}
.cover-meta {{ font-size: 9pt; color: {MUTE}; border-top: .4mm solid {RULE}; padding-top: 4mm;
               max-width: 125mm; }}
.cover-meta b {{ color: {INK}; font-weight: 600; }}

/* ---- contents ---- */
.toc {{ page: frontmatter; break-after: page; }}
.toc h2 {{ font-size: 15pt; color: {INK}; margin: 0 0 6mm 0; border: 0; padding: 0; }}
.toc ol {{ list-style: none; margin: 0; padding: 0; }}
.toc li {{ margin: 0 0 1.3mm 0; font-size: 10pt; }}
.toc li.part {{ margin: 5mm 0 2mm 0; font-family: "Noto Sans", "DejaVu Sans", sans-serif;
                font-size: 8.5pt; letter-spacing: .1em; text-transform: uppercase;
                color: {GOLD}; }}
.toc li.sub {{ padding-left: 9mm; font-size: 9.2pt; color: {MUTE}; }}
.toc a {{ color: inherit; text-decoration: none; }}
.toc .row {{ display: flex; align-items: baseline; gap: 2mm; }}
.toc .num {{ color: {MUTE}; min-width: 9mm; }}
.toc .dots {{ flex: 1; border-bottom: .25mm dotted {RULE}; }}
.toc a::after {{ content: target-counter(attr(href), page); color: {MUTE}; }}

/* ---- parts and headings ---- */
.part-page {{ break-before: page; break-after: page; padding-top: 78mm; }}
.part-rule {{ width: 26mm; height: 1.4mm; background: {GOLD}; margin-bottom: 8mm; }}
.part-title {{ font-size: 26pt; font-weight: 700; margin: 0; letter-spacing: -.3pt; }}

h2 {{ font-size: 16pt; color: {INK}; margin: 12mm 0 3mm 0; font-weight: 700;
      break-after: avoid; padding-bottom: 2mm; border-bottom: .35mm solid {RULE}; }}
h2 .num {{ color: {GOLD}; margin-right: 3mm; }}
h3 {{ font-size: 11.5pt; color: {GOLD}; margin: 7mm 0 2mm 0; font-weight: 600;
      break-after: avoid; }}
h3 .num {{ color: {MUTE}; margin-right: 2.5mm; font-weight: 400; }}

p {{ margin: 0 0 3mm 0; orphans: 2; widows: 2; }}
ol {{ margin: 0 0 3mm 0; padding-left: 6mm; }}
li {{ margin: 0 0 1.6mm 0; orphans: 2; widows: 2; }}
ul {{ list-style: none; margin: 0 0 3mm 0; padding-left: 5mm; }}
ul > li {{ position: relative; padding-left: 4mm; }}
ul > li::before {{ content: "\\2014"; position: absolute; left: 0; color: {GOLD}; }}

.note {{ background: {WASH}; border-left: 1mm solid {GOLD}; padding: 3mm 4mm;
         margin: 4mm 0; font-size: 9.6pt; break-inside: avoid; }}
.note .kicker {{ display: block; font-size: 7.5pt; letter-spacing: .1em;
                 text-transform: uppercase; color: {GOLD}; margin-bottom: 1.2mm; }}

table {{ border-collapse: collapse; width: 100%; margin: 3mm 0 5mm 0;
         font-size: 9.2pt; }}
thead {{ display: table-header-group; }}
tr {{ break-inside: avoid; }}
caption {{ caption-side: top; text-align: left;
           font-family: "Noto Sans", "DejaVu Sans", sans-serif;
           font-size: 8pt; letter-spacing: .08em; text-transform: uppercase;
           color: {MUTE}; padding-bottom: 1.8mm; break-after: avoid; }}
th {{ text-align: left; font-size: 8pt; letter-spacing: .05em; text-transform: uppercase;
      color: {MUTE}; font-weight: 600; border-bottom: .4mm solid {INK}; padding: 1.8mm 2.5mm; }}
td {{ border-bottom: .25mm solid {RULE}; padding: 1.8mm 2.5mm; vertical-align: top; }}
tbody tr:nth-child(even) {{ background: {WASH}; }}
"""


def cover_html():
	bars = "".join(
		f'<span class="bar" style="height:{h}mm"></span>' for h in (5, 8, 11)
	)
	return f"""
<section class="cover">
  <div class="cover-band">
    <div class="cover-mark">{bars}</div>
    <h1>{html.escape(content.TITLE)}</h1>
    <p class="sub">{html.escape(content.SUBTITLE)}</p>
  </div>
  <div class="cover-body">
    <p class="cover-strap">{html.escape(content.STRAPLINE)}</p>
    <div class="cover-meta">
      <b>Part I</b> is for everyone using the system day to day.<br>
      <b>Part II</b> is for whoever sets it up on a new project.<br><br>
      A living document — regenerated from the system it describes.
    </div>
  </div>
</section>"""


def toc_html(blocks):
	rows = []
	for kind, payload, number, anchor in blocks:
		if kind == "part":
			rows.append(f'<li class="part">{html.escape(payload)}</li>')
		elif kind in ("h2", "h3"):
			cls = "sub" if kind == "h3" else ""
			rows.append(
				f'<li class="{cls}"><div class="row">'
				f'<span class="num">{number}</span>'
				f"<span>{html.escape(payload)}</span>"
				f'<span class="dots"></span>'
				f'<a href="#{anchor}"></a>'
				f"</div></li>"
			)
	return '<section class="toc"><h2>Contents</h2><ol>' + "".join(rows) + "</ol></section>"


def table_html(payload):
	caption, headers, rows = payload
	head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
	body = "".join(
		"<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>"
		for row in rows
	)
	return (
		f"<table><caption>{html.escape(caption)}</caption>"
		f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
	)


def body_html(blocks):
	out = []
	pending_list = None

	def close_list():
		nonlocal pending_list
		if pending_list:
			out.append(f"</{pending_list}>")
			pending_list = None

	def open_list(tag):
		nonlocal pending_list
		if pending_list != tag:
			close_list()
			out.append(f"<{tag}>")
			pending_list = tag

	for kind, payload, number, anchor in blocks:
		if kind in ("b", "n"):
			open_list("ul" if kind == "b" else "ol")
			out.append(f"<li>{html.escape(payload)}</li>")
			continue
		close_list()
		if kind == "part":
			out.append(
				f'<div class="part-page"><div class="part-rule"></div>'
				f'<h1 class="part-title">{html.escape(payload)}</h1></div>'
			)
		elif kind == "h2":
			out.append(
				f'<h2 id="{anchor}"><span class="num">{number}</span>{html.escape(payload)}</h2>'
			)
		elif kind == "h3":
			out.append(
				f'<h3 id="{anchor}"><span class="num">{number}</span>{html.escape(payload)}</h3>'
			)
		elif kind == "note":
			out.append(
				f'<div class="note"><span class="kicker">Note</span>{html.escape(payload)}</div>'
			)
		elif kind == "table":
			out.append(table_html(payload))
		else:
			out.append(f"<p>{html.escape(payload)}</p>")
	close_list()
	return "<article>" + "".join(out) + "</article>"


def build_pdf(blocks):
	from weasyprint import CSS as WeasyCSS
	from weasyprint import HTML as WeasyHTML

	page = (
		"<!doctype html><html><head><meta charset='utf-8'>"
		f"<title>{html.escape(content.TITLE)} — {html.escape(content.SUBTITLE)}</title>"
		"</head><body>"
		+ cover_html()
		+ toc_html(blocks)
		+ body_html(blocks)
		+ "</body></html>"
	)
	WeasyHTML(string=page, base_url=str(ROOT)).write_pdf(
		PDF_OUT, stylesheets=[WeasyCSS(string=CSS)]
	)
	return PDF_OUT


# ---------------------------------------------------------------------- DOCX


def build_docx(blocks):
	from docx import Document
	from docx.enum.text import WD_ALIGN_PARAGRAPH
	from docx.shared import Pt, RGBColor

	ink = RGBColor(0x0A, 0x0A, 0x0A)
	gold = RGBColor(0xA0, 0x60, 0x00)
	mute = RGBColor(0x6F, 0x6D, 0x65)

	doc = Document()
	style = doc.styles["Normal"]
	style.font.name = "Calibri"
	style.font.size = Pt(10.5)

	heading = doc.add_heading(f"{content.TITLE} — {content.SUBTITLE}", level=0)
	for run in heading.runs:
		run.font.color.rgb = ink
	strap = doc.add_paragraph(content.STRAPLINE)
	strap.alignment = WD_ALIGN_PARAGRAPH.LEFT
	for run in strap.runs:
		run.font.color.rgb = mute
		run.font.size = Pt(9)

	for kind, payload, number, _anchor in blocks:
		if kind == "part":
			para = doc.add_heading(payload, level=1)
			for run in para.runs:
				run.font.color.rgb = ink
		elif kind == "h2":
			para = doc.add_heading(f"{number}. {payload}", level=2)
			for run in para.runs:
				run.font.color.rgb = gold
		elif kind == "h3":
			para = doc.add_heading(f"{number} {payload}", level=3)
			for run in para.runs:
				run.font.color.rgb = ink
		elif kind == "b":
			doc.add_paragraph(payload, style="List Bullet")
		elif kind == "n":
			doc.add_paragraph(payload, style="List Number")
		elif kind == "note":
			para = doc.add_paragraph(f"Note — {payload}")
			for run in para.runs:
				run.font.color.rgb = gold
				run.font.size = Pt(9.5)
		elif kind == "table":
			caption, headers, rows = payload
			cap = doc.add_paragraph(caption)
			for run in cap.runs:
				run.font.color.rgb = mute
				run.font.size = Pt(8.5)
			table = doc.add_table(rows=1, cols=len(headers))
			table.style = "Light Grid Accent 1"
			for cell, header in zip(table.rows[0].cells, headers):
				cell.text = str(header)
			for row in rows:
				cells = table.add_row().cells
				for cell, value in zip(cells, row):
					cell.text = str(value)
			doc.add_paragraph()
		else:
			doc.add_paragraph(payload)

	doc.save(DOCX_OUT)
	return DOCX_OUT


def main():
	blocks = numbered(content.sections())
	for path in (build_pdf(blocks), build_docx(blocks)):
		print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
	main()
