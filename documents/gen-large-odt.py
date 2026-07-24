#!/usr/bin/env python3
"""Generate a ~10 MB ODT test document: text, images, tables and graphs.

Size in an ODT is driven by embedded raster images, so the script fills the
body with sections (headings + prose + a data table + a figure), scatters
matplotlib charts through it, then pads an appendix with generated images until
the embedded-image bytes reach the target. Meant as a load/render test fixture,
not a design showcase.
"""
import io
import os
import math
import random
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image as PILImage, ImageDraw

from odf.opendocument import OpenDocumentText
from odf.style import (Style, TextProperties, ParagraphProperties, FontFace,
                       GraphicProperties, TableProperties, TableColumnProperties,
                       TableCellProperties, MasterPage, PageLayout,
                       PageLayoutProperties)
from odf.text import P, H
from odf.table import Table, TableColumn, TableRow, TableCell
from odf.draw import Frame, Image
from odf import teletype

random.seed(1234)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "large-mixed-10mb.odt")
TARGET_IMAGE_BYTES = int(9.6 * 1024 * 1024)   # rest of the file (~0.4 MB) is xml/overhead
ASSETS = tempfile.mkdtemp(prefix="odt-assets-")

ACCENT, DARK, LIGHT, GREY = "#5c2983", "#2e1a47", "#efe7f3", "#8b8b89"
FONT = "Carlito"

LOREM = (
    "The quick brown fox jumps over the lazy dog while the collaborative editor "
    "reflows the paragraph and repaints the affected tiles. Real-time editing "
    "keeps every view in sync as text is inserted, styles are applied and tables "
    "are resized. This document exists to exercise loading, layout and rendering "
    "of a large mixed-content file across the whole stack."
)

doc = OpenDocumentText()
doc.fontfacedecls.addElement(FontFace(name=FONT, fontfamily=FONT,
                                      fontfamilygeneric="swiss", fontpitch="variable"))

# ---- page layout ----
pl = PageLayout(name="PL")
pl.addElement(PageLayoutProperties(pagewidth="21.001cm", pageheight="29.7cm",
                                   margintop="2cm", marginbottom="2cm",
                                   marginleft="2cm", marginright="2cm"))
doc.automaticstyles.addElement(pl)
mp = MasterPage(name="Standard", pagelayoutname=pl)
doc.masterstyles.addElement(mp)

def pstyle(name, size, color=None, weight="normal", above=0.0, below=0.0, align="justify"):
    s = Style(name=name, family="paragraph")
    s.addElement(ParagraphProperties(margintop=f"{above}cm", marginbottom=f"{below}cm",
                                     textalign=align, orphans="2", widows="2"))
    tp = {"fontsize": f"{size}pt", "fontweight": weight, "fontname": FONT}
    if color:
        tp["color"] = color
    s.addElement(TextProperties(**tp))
    doc.styles.addElement(s)
    return name

TITLE = pstyle("Title", 30, ACCENT, "bold", 0, 0.6, "center")
H1 = pstyle("Heading 1", 20, ACCENT, "bold", 0.8, 0.3, "start")
H2 = pstyle("Heading 2", 15, DARK, "bold", 0.5, 0.2, "start")
BODY = pstyle("Body Text", 11, "#1a1a1a", "normal", 0.0, 0.25)
CAPTION = pstyle("Caption", 9, GREY, "italic", 0.1, 0.5, "center")
FIGP = pstyle("Figure", 11, align="center", above=0.3)

# ---- table styles ----
tbl = Style(name="Tbl", family="table")
tbl.addElement(TableProperties(width="17cm", align="center"))
doc.automaticstyles.addElement(tbl)
col = Style(name="Col", family="table-column")
col.addElement(TableColumnProperties(columnwidth="3.4cm"))
doc.automaticstyles.addElement(col)
def cellstyle(name, bg, color, weight):
    s = Style(name=name, family="table-cell")
    s.addElement(TableCellProperties(backgroundcolor=bg, padding="0.15cm",
                                     border="0.5pt solid #cccccc"))
    doc.automaticstyles.addElement(s)
    cp = Style(name=name + "P", family="paragraph")
    cp.addElement(TextProperties(fontsize="10pt", fontweight=weight, color=color, fontname=FONT))
    doc.automaticstyles.addElement(cp)
    return name, name + "P"
HCELL, HCELLP = cellstyle("HCell", DARK, "#ffffff", "bold")
BCELL, BCELLP = cellstyle("BCell", "#ffffff", "#1a1a1a", "normal")
ACELL, ACELLP = cellstyle("ACell", LIGHT, "#1a1a1a", "normal")

gframe = Style(name="Gr", family="graphic")
gframe.addElement(GraphicProperties(border="none"))
doc.automaticstyles.addElement(gframe)

embedded_bytes = 0
def add_image(path, w_cm=16.0):
    """Embed an image as a centered figure; returns its byte size."""
    global embedded_bytes
    with PILImage.open(path) as im:
        w, h = im.size
    h_cm = w_cm * h / w
    p = P(stylename=FIGP)
    fr = Frame(stylename=gframe, width=f"{w_cm}cm", height=f"{h_cm:.2f}cm",
               anchortype="as-char")
    fr.addElement(Image(href=doc.addPicture(path)))
    p.addElement(fr)
    doc.text.addElement(p)
    n = os.path.getsize(path)
    embedded_bytes += n
    return n

def add_para(text, style=BODY):
    p = P(stylename=style)
    teletype.addTextToElement(p, text)
    doc.text.addElement(p)

def add_heading(text, level, style):
    h = H(outlinelevel=level, stylename=style)
    teletype.addTextToElement(h, text)
    doc.text.addElement(h)

def add_caption(text):
    add_para(text, CAPTION)

def add_table(rows, cols, title):
    t = Table(name=title, stylename=tbl)
    t.addElement(TableColumn(numbercolumnsrepeated=str(cols), stylename=col))
    # header
    hr = TableRow()
    for c in range(cols):
        cell = TableCell(stylename=HCELL)
        p = P(stylename=HCELLP)
        teletype.addTextToElement(p, ["Metric", "Q1", "Q2", "Q3", "Q4"][c] if c < 5 else f"C{c}")
        cell.addElement(p)
        hr.addElement(cell)
    t.addElement(hr)
    for r in range(rows):
        row = TableRow()
        for c in range(cols):
            cs, cps = (ACELL, ACELLP) if r % 2 else (BCELL, BCELLP)
            cell = TableCell(stylename=cs)
            p = P(stylename=cps)
            val = f"row {r + 1}" if c == 0 else f"{random.uniform(10, 9999):.2f}"
            teletype.addTextToElement(p, val)
            cell.addElement(p)
            row.addElement(cell)
        t.addElement(row)
    doc.text.addElement(t)

# ---- asset generators ----
def make_figure(i):
    """A colourful gradient + shapes + noise figure (JPEG, ~0.3 MB). numpy for
    the gradient/noise so it is fast; the noise keeps the JPEG from collapsing."""
    w, h = 1500, 1000
    xr = np.arange(w, dtype=np.uint16)
    yr = np.arange(h, dtype=np.uint16)
    R = np.broadcast_to(((xr * 255 // w + random.randint(0, 200)) % 256).astype(np.uint8)[None, :], (h, w))
    G = np.broadcast_to(((yr * 255 // h + random.randint(0, 200)) % 256).astype(np.uint8)[:, None], (h, w))
    B = ((R.astype(np.uint16) + G) // 2).astype(np.uint8)
    arr = np.dstack([R, G, B]).astype(np.uint16)
    noise = np.random.randint(0, 256, (h, w, 3), dtype=np.uint16)
    arr = ((arr * 82 + noise * 18) // 100).astype(np.uint8)
    base = PILImage.fromarray(arr, "RGB")
    d = ImageDraw.Draw(base, "RGBA")
    for _ in range(70):
        x1, y1 = random.randint(0, w), random.randint(0, h)
        x2, y2 = x1 + random.randint(40, 350), y1 + random.randint(40, 260)
        col = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255),
               random.randint(60, 150))
        (d.ellipse if random.random() < 0.5 else d.rectangle)([x1, y1, x2, y2], fill=col)
    d.text((30, 30), f"Figure {i} - synthetic test image", fill=(255, 255, 255))
    path = os.path.join(ASSETS, f"fig{i}.jpg")
    base.save(path, "JPEG", quality=80)
    return path

def make_chart(i, kind):
    fig, ax = plt.subplots(figsize=(8, 4.6), dpi=150)
    xs = list(range(1, 13))
    if kind == "bar":
        ax.bar(xs, [random.uniform(5, 100) for _ in xs], color="#5c2983")
        ax.set_title("Monthly tile invalidations")
    elif kind == "line":
        for lbl in ("load", "edit", "save"):
            ax.plot(xs, [random.uniform(10, 100) for _ in xs], marker="o", label=lbl)
        ax.legend(); ax.set_title("Latency by operation (ms)")
    elif kind == "pie":
        ax.pie([random.uniform(1, 5) for _ in range(5)],
               labels=["parse", "layout", "paint", "io", "other"], autopct="%1.0f%%")
        ax.set_title("CPU time breakdown")
    elif kind == "scatter":
        ax.scatter([random.uniform(0, 100) for _ in range(200)],
                   [random.uniform(0, 100) for _ in range(200)], c="#40ba2f", alpha=0.5)
        ax.set_title("Users vs response time")
    else:  # stacked
        a = [random.uniform(5, 40) for _ in xs]; b = [random.uniform(5, 40) for _ in xs]
        ax.bar(xs, a, label="kit", color="#5c2983")
        ax.bar(xs, b, bottom=a, label="wsd", color="#40ba2f")
        ax.legend(); ax.set_title("CPU per component")
    ax.set_xlabel("period"); ax.grid(True, alpha=0.3)
    path = os.path.join(ASSETS, f"chart{i}.png")
    fig.tight_layout(); fig.savefig(path); plt.close(fig)
    return path

# ---- build the document ----
add_para("Large Mixed-Content Test Document", TITLE)
add_para("A ~10 MB ODT with text, images, tables and graphs, for load and "
         "rendering tests. Generated content; not for publication.", CAPTION)

chart_kinds = ["bar", "line", "pie", "scatter", "stacked"]
fig_i = chart_i = 0
SECTIONS = 16
for s in range(1, SECTIONS + 1):
    add_heading(f"{s}. Section {s}: collaborative editing under load", 1, H1)
    for _ in range(random.randint(3, 5)):
        add_para(LOREM + " " + LOREM[: random.randint(80, 260)])
    add_heading(f"{s}.1 Measurements", 2, H2)
    add_table(random.randint(6, 12), 5, f"tbl{s}")
    add_caption(f"Table {s}: sampled metrics for section {s}.")
    # alternate a figure and a graph through the body; the appendix pads the rest
    if s % 2:
        fig_i += 1
        add_image(make_figure(fig_i))
        add_caption(f"Figure {fig_i}: synthetic illustration.")
    else:
        chart_i += 1
        k = chart_kinds[chart_i % len(chart_kinds)]
        add_image(make_chart(chart_i, k), w_cm=15)
        add_caption(f"Graph {chart_i}: {k} chart.")

# ---- pad to target with an image appendix ----
add_heading("Appendix A: figure gallery", 1, H1)
add_para("Additional figures included to reach the target file size.", BODY)
while embedded_bytes < TARGET_IMAGE_BYTES:
    fig_i += 1
    add_image(make_figure(fig_i))
    add_caption(f"Figure {fig_i}: synthetic illustration.")

doc.save(OUT)
size = os.path.getsize(OUT)
print(f"wrote {OUT}")
print(f"size: {size/1024/1024:.2f} MB  (embedded images ~{embedded_bytes/1024/1024:.2f} MB, "
      f"{fig_i} figures, {chart_i} charts, {SECTIONS} sections)")
