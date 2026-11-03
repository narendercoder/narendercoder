#!/usr/bin/env python3
"""Render the 2026 sports current-affairs Markdown guides as styled A4 PDFs.

Usage:
    PYTHONPATH=/tmp/pdfdeps python3 tools/md_to_pdf.py

Dependencies (installed into /tmp/pdfdeps in this workspace):
    pip install --target /tmp/pdfdeps reportlab markdown beautifulsoup4 fonttools

Design notes:
  * DejaVu Sans is embedded, so accented names, arrows, primes and the pound/euro
    signs render correctly. Emoji and Devanagari are not in DejaVu, so emoji are
    replaced with text labels and the handful of Hindi mnemonic phrases are
    transliterated to Roman script (the Markdown files keep the originals).
  * Markdown -> HTML (python-markdown) -> reportlab Platypus flowables, with
    auto-sized, repeating-header tables, a linked table of contents and PDF
    outline bookmarks.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import markdown as md
from bs4 import BeautifulSoup, NavigableString, Tag
from fontTools.ttLib import TTFont as FontToolsFont
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

NAVY = colors.HexColor("#0f2b46")
NAVY_LIGHT = colors.HexColor("#1d4ed8")
TEAL = colors.HexColor("#0e7490")
AMBER = colors.HexColor("#b45309")
INK = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#64748b")
GRID = colors.HexColor("#d6e0ea")
PALE = colors.HexColor("#f2f7fb")
PALE_AMBER = colors.HexColor("#fff8ed")
WHITE = colors.white

MARGIN = 14 * mm
AVAIL = A4[0] - 2 * MARGIN

# --------------------------------------------------------------------------- #
# Fonts
# --------------------------------------------------------------------------- #

pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("DejaVuMono", str(FONT_DIR / "DejaVuSansMono.ttf")))
pdfmetrics.registerFont(TTFont("DejaVuSerif", str(FONT_DIR / "DejaVuSerif.ttf")))
pdfmetrics.registerFontFamily(
    "DejaVu",
    normal="DejaVu",
    bold="DejaVu-Bold",
    italic="DejaVu",
    boldItalic="DejaVu-Bold",
)
_CMAP = FontToolsFont(str(FONT_DIR / "DejaVuSans.ttf")).getBestCmap()

# --------------------------------------------------------------------------- #
# Styles
# --------------------------------------------------------------------------- #

S = {
    "Body": ParagraphStyle(
        "Body", fontName="DejaVu", fontSize=8.9, leading=12.4, spaceAfter=4,
        textColor=INK, alignment=TA_LEFT, splitLongWords=1,
    ),
    "H1": ParagraphStyle(
        "H1", fontName="DejaVu-Bold", fontSize=15, leading=19, spaceBefore=12,
        spaceAfter=7, textColor=NAVY,
    ),
    "H2": ParagraphStyle(
        "H2", fontName="DejaVu-Bold", fontSize=11.3, leading=15, spaceBefore=10,
        spaceAfter=5, textColor=TEAL,
    ),
    "H3": ParagraphStyle(
        "H3", fontName="DejaVu-Bold", fontSize=9.6, leading=13, spaceBefore=7,
        spaceAfter=4, textColor=NAVY,
    ),
    "Cell": ParagraphStyle(
        "Cell", fontName="DejaVu", fontSize=7.35, leading=9.5, spaceAfter=0,
        textColor=INK, splitLongWords=1,
    ),
    "CellC": ParagraphStyle(
        "CellC", parent=ParagraphStyle("tmp"), fontName="DejaVu", fontSize=7.35,
        leading=9.5, spaceAfter=0, textColor=INK, alignment=TA_CENTER,
        splitLongWords=1,
    ),
    "CellH": ParagraphStyle(
        "CellH", fontName="DejaVu-Bold", fontSize=7.5, leading=9.7, spaceAfter=0,
        textColor=WHITE, splitLongWords=1,
    ),
    "Bullet": ParagraphStyle(
        "Bullet", fontName="DejaVu", fontSize=8.5, leading=11.6, spaceAfter=2.5,
        textColor=INK, leftIndent=11, bulletIndent=2, splitLongWords=1,
    ),
    "Quote": ParagraphStyle(
        "Quote", fontName="DejaVu", fontSize=8.6, leading=11.8, spaceAfter=0,
        textColor=INK, splitLongWords=1,
    ),
    "Small": ParagraphStyle(
        "Small", fontName="DejaVu", fontSize=7.8, leading=10.6, spaceAfter=3,
        textColor=MUTED, splitLongWords=1,
    ),
    "CoverKicker": ParagraphStyle(
        "CoverKicker", fontName="DejaVu-Bold", fontSize=9, leading=13,
        textColor=TEAL, spaceAfter=4,
    ),
    "CoverNote": ParagraphStyle(
        "CoverNote", fontName="DejaVu", fontSize=8.7, leading=12.4,
        textColor=INK, spaceAfter=0,
    ),
    "TOCTitle": ParagraphStyle(
        "TOCTitle", fontName="DejaVu-Bold", fontSize=15, leading=19,
        spaceAfter=9, textColor=NAVY,
    ),
    "TOC1": ParagraphStyle(
        "TOC1", fontName="DejaVu-Bold", fontSize=10, leading=15, spaceBefore=7,
        textColor=NAVY,
    ),
    "TOC2": ParagraphStyle(
        "TOC2", fontName="DejaVu", fontSize=8.6, leading=12, leftIndent=12,
        textColor=INK,
    ),
}

# --------------------------------------------------------------------------- #
# Text cleanup: emoji -> labels, Hindi -> transliteration, superscripts -> ASCII
# --------------------------------------------------------------------------- #

EMOJI_LABELS = {
    "🏆": "★", "🏅": "★", "🥇": "GOLD", "🥉": "BRONZE",
    "🧠": "MNEMONIC:", "🔜": "UPCOMING:", "🔑": "KEY:", "✅": "",
    "⚠️": "", "⚠": "", "⚡": "", "🔄": "ongoing", "🆚": "vs",
    "🗓️": "", "🗓": "", "❄️": "", "❄": "", "♟️": "", "♟": "",
    "📌": "", "📖": "", "📅": "", "📊": "", "🔗": "", "📝": "",
    "🏏": "", "🏸": "", "⚽": "", "🎾": "", "🏑": "", "🧊": "", "🌍": "",
    "🇮": "", "🇳": "", "⃣": "",
}
KEEP_SYMBOLS = set("⚠✓★→←≠×′·—–…£€²§")

HINDI = [
    # longest first so composite phrases are replaced before their parts
    ("**तीन-नौ (39) → पचासी (85) → एक सौ चौदह (114), तीनों में चौथा (4th)**",
     "**teen-nau (39) → pachaasi (85) → ek sau chaudah (114), teenon mein chautha (4th)**"),
    ("**तीन-नौ (39) → पचासी (85) → एक सौ चौदह (114)**",
     "**teen-nau (39) → pachaasi (85) → ek sau chaudah (114)**"),
    ("**छह-नब्बे (96) से तीसरी बार, संजू ने 321**",
     "**chhah-nabbe (96) se teesri baar, Sanju ne 321**"),
    ("**च**ीन थॉमस, **क**ोरिया उबर, **द**िल्ली वर्ल्ड",
     "**C**heen Thomas, **K**orea Uber, **D**illi Worlds"),
    ("**ज**नवरी **प**द्म, **ज**ुलाई **ह**ॉल, **अ**गस्त **अ**र्जुन, **अ**क्टूबर **ब**ैलन",
     "**J**an Padma, **J**ul Hall, **A**ug Arjuna, **O**ct Ballon"),
    ("**चाय-हॉकी-कबड्डी, दो-दो गोल्ड**", "**CHK — do-do gold**"),
    ("(तीन-नौ, पचासी, एक सौ चौदह)", "(teen-nau, pachaasi, ek sau chaudah)"),
    ("**खाली खेल, सत्तरह अर्जुन**", "**khaali khel, sattarah Arjuna**"),
    ("**तीनों में चौथा**", "**teenon mein chautha**"),
    ('"तीनों में चौथा"', '"teenon mein chautha"'),
    ("तीनों में चौथा", "teenon mein chautha"),
    ("खाली खेल, सत्तरह अर्जुन", "khaali khel, sattarah Arjuna"),
    ("तीन-नौ", "teen-nau"), ("पचासी", "pachaasi"),
    ("एक सौ चौदह", "ek sau chaudah"), ("चौथा", "chautha"),
]

DEVANAGARI_MAP = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "च": "ch", "छ": "chh",
    "ज": "j", "झ": "jh", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p",
    "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
    "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "े": "e",
    "ै": "ai", "ो": "o", "ौ": "au", "्": "", "ं": "n", "ँ": "n",
    "ॉ": "o", "ः": "h",
}
SUPERSCRIPTS = {
    "⁽": "(", "⁾": ")", "⁻": "-", "⁰": "0", "¹": "1", "²": "2",
    "³": "3", "⁴": "4", "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
}


def clean_markdown(text: str) -> str:
    # The <details> block hides the MCQ answer key from reportlab; flatten it.
    text = re.sub(
        r"<details>\s*<summary>.*?</summary>\s*",
        "### Answer key + one-line explanations\n\n",
        text,
        flags=re.S,
    )
    text = text.replace("</details>", "")

    # Emoji -> short text labels.
    for key in sorted(EMOJI_LABELS, key=len, reverse=True):
        text = text.replace(key, EMOJI_LABELS[key])
    # Keycap digits such as 1️⃣ -> "1."
    text = re.sub(r"([0-9])\ufe0f?\u20e3", r"\1.", text)
    # Tennis tiebreak superscripts -> plain parentheses.
    for k, v in SUPERSCRIPTS.items():
        text = text.replace(k, v)

    for a, b in HINDI:
        text = text.replace(a, b)

    # Remove the duplicated marker created by the source blockquote.
    text = text.replace(
        "flagged as UPCOMING: **Upcoming** and are not presented as results",
        "flagged as **UPCOMING** and are not presented as results",
    )
    text = text.replace(
        "UPCOMING: **Upcoming (do NOT treat as a result)**",
        "**UPCOMING — do NOT treat as a result**",
    )

    out = []
    for ch in text:
        cp = ord(ch)
        if cp in (0xFE0F, 0x200D, 0x20E3):
            continue
        if 0x1F000 <= cp <= 0x1FAFF or 0x1F1E6 <= cp <= 0x1F1FF:
            continue
        if 0x2600 <= cp <= 0x27BF and ch not in KEEP_SYMBOLS:
            continue
        if 0x0900 <= cp <= 0x097F:  # any leftover Devanagari
            ch = DEVANAGARI_MAP.get(ch, "")
        if ord(ch) > 127 and ord(ch) not in _CMAP:
            ch = ""  # never emit a missing glyph
        out.append(ch)
    text = "".join(out)
    return tidy_headings(text)


# Labels that are useful inline but clutter headings and the table of contents.
HEADING_NOISE = (
    "MNEMONIC: ", "NOTE: ", "UPCOMING: ", "KEY: ", "GOLD ", "BRONZE ",
    "ongoing ", "★ ", "✓ ", "• ",
)


def tidy_headings(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if re.match(r"^#{1,4}\s", line):
            for token in HEADING_NOISE:
                line = line.replace(token, "")
            line = re.sub(r"[ \t]{2,}", " ", line).rstrip()
        lines.append(line)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HTML -> reportlab inline markup
# --------------------------------------------------------------------------- #

def inline(node: Tag) -> str:
    parts = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(html.escape(re.sub(r"\s+", " ", str(child)), quote=False))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        inner = inline(child)
        if name in ("b", "strong"):
            parts.append(f"<b>{inner}</b>")
        elif name in ("i", "em"):
            parts.append(f"<i>{inner}</i>")
        elif name == "code":
            parts.append(f'<font face="DejaVuMono" size="7.2">{inner}</font>')
        elif name == "a":
            href = html.escape(child.get("href", ""), quote=True)
            parts.append(f'<a href="{href}" color="#1d4ed8">{inner}</a>')
        elif name == "br":
            parts.append("<br/>")
        elif name == "sup":
            parts.append(f"<super>{inner}</super>")
        else:
            parts.append(inner)
    return "".join(parts).strip()


def plain(node: Tag) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def col_widths(rows: list[list[str]], ncols: int) -> list[float]:
    weights = []
    for c in range(ncols):
        lengths = [len(r[c]) for r in rows if c < len(r)] or [10]
        avg = sum(lengths) / len(lengths)
        weights.append(min(max(avg * 0.7 + max(lengths) * 0.3, 9), 90))
    widths = [AVAIL * w / sum(weights) for w in weights]
    for _ in range(3):
        minw = 12 * mm
        widths = [max(w, minw) for w in widths]
        scale = AVAIL / sum(widths)
        widths = [w * scale for w in widths]
    return [AVAIL * w / sum(widths) for w in widths]


def build_table(el: Tag) -> Table:
    head = el.find("thead")
    body = el.find("tbody") or el
    header_cells = head.find_all("th") if head else []
    trs = body.find_all("tr") if body else []
    if head:
        trs = [r for r in trs if r.find_parent("thead") is None]

    aligns = []
    for th in header_cells:
        style = (th.get("style") or "").replace(" ", "")
        aligns.append("center" if "center" in style else ("right" if "right" in style else "left"))

    data, text_rows = [], []
    if header_cells:
        data.append([Paragraph(inline(c), S["CellH"]) for c in header_cells])
        text_rows.append([plain(c) for c in header_cells])
    ncols = len(header_cells) if header_cells else (len(trs[0].find_all(["td", "th"])) if trs else 1)
    for tr in trs:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row = []
        for i, c in enumerate(cells):
            st = S["CellC"] if i < len(aligns) and aligns[i] == "center" else S["Cell"]
            row.append(Paragraph(inline(c), st))
        data.append(row)
        text_rows.append([plain(c) for c in cells])

    widths = col_widths(text_rows, ncols)
    t = Table(data, colWidths=widths, repeatRows=1 if header_cells else 0, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.35, GRID),
        ("BOX", (0, 0), (-1, -1), 0.7, NAVY),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
    ]
    if header_cells:
        cmds += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, TEAL),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE]),
        ]
    else:
        cmds.append(("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, PALE]))
    t.setStyle(TableStyle(cmds))
    return t


def build_quote(el: Tag) -> Table:
    content = "<br/>".join(inline(p) for p in el.find_all("p", recursive=False)) or inline(el)
    p = Paragraph(content, S["Quote"])
    t = Table([[p]], colWidths=[AVAIL])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
        ("LINEBEFORE", (0, 0), (0, 0), 2.4, AMBER),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def html_to_story(text: str) -> list:
    soup = BeautifulSoup(text, "html.parser")
    root = soup.body or soup  # html.parser does not add an implicit <body>
    story = []
    h1_seen = False
    for el in root.find_all(recursive=False):
        if not isinstance(el, Tag):
            continue
        name = el.name.lower()
        txt = inline(el)
        if not txt:
            continue
        if name == "h1":
            if not h1_seen:  # the cover already carries the title
                h1_seen = True
            continue
        elif name == "h2":
            story.append(Paragraph(txt, S["H1"]))
        elif name == "h3":
            story.append(Paragraph(txt, S["H2"]))
        elif name == "h4":
            story.append(Paragraph(txt, S["H3"]))
        elif name == "p":
            story.append(Paragraph(txt, S["Body"]))
        elif name == "blockquote":
            story.append(Spacer(1, 3))
            story.append(build_quote(el))
            story.append(Spacer(1, 5))
        elif name == "table":
            story.append(Spacer(1, 2))
            story.append(build_table(el))
            story.append(Spacer(1, 6))
        elif name in ("ul", "ol"):
            for i, li in enumerate(el.find_all("li", recursive=False), 1):
                bullet = f"{i}." if name == "ol" else "•"
                story.append(Paragraph(inline(li), S["Bullet"], bulletText=bullet))
            story.append(Spacer(1, 3))
        elif name == "hr":
            continue
        else:
            story.append(Paragraph(txt, S["Body"]))
    return story


# --------------------------------------------------------------------------- #
# Document template: cover, TOC, header/footer, bookmarks
# --------------------------------------------------------------------------- #

class GuideDoc(BaseDocTemplate):
    def __init__(self, filename, cover_title, cover_subtitle, cover_banner, **kw):
        super().__init__(filename, pagesize=A4, **kw)
        self.doc_title = cover_title
        self.doc_subtitle = cover_subtitle
        self.banner_sub = cover_banner
        self._bm = 0
        frame = Frame(MARGIN, MARGIN, AVAIL, A4[1] - 2 * MARGIN,
                      id="body", leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self.first_page),
            PageTemplate(id="normal", frames=[frame], onPage=self.later_pages),
        ])

    def first_page(self, canvas, doc):
        canvas.saveState()
        h = 62 * mm
        canvas.setFillColor(NAVY)
        canvas.rect(0, A4[1] - h, A4[0], h, fill=1, stroke=0)
        canvas.setFillColor(TEAL)
        canvas.rect(0, A4[1] - h, A4[0], 2.6 * mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont("DejaVu-Bold", 22)
        canvas.drawString(18 * mm, A4[1] - 27 * mm, self.doc_title)
        canvas.setFont("DejaVu", 10.5)
        canvas.setFillColor(colors.HexColor("#c7e6f2"))
        canvas.drawString(18 * mm, A4[1] - 38 * mm, self.doc_subtitle)
        canvas.setFont("DejaVu", 8.6)
        canvas.setFillColor(colors.HexColor("#9fb8cc"))
        canvas.drawString(18 * mm, A4[1] - 48 * mm, self.banner_sub)
        canvas.setFillColor(MUTED)
        canvas.setFont("DejaVu", 7.6)
        canvas.drawCentredString(A4[0] / 2, 9 * mm,
                                 "Generated from the Markdown study notes · Hindi phrases transliterated for PDF")
        canvas.restoreState()

    def later_pages(self, canvas, doc):
        canvas.saveState()
        canvas.setFont("DejaVu-Bold", 7.4)
        canvas.setFillColor(MUTED)
        canvas.drawString(MARGIN, A4[1] - 9.5 * mm,
                          "SPORTS CURRENT AFFAIRS 2026  ·  JAN–NOV  ·  EXAM NOTES")
        canvas.drawRightString(A4[0] - MARGIN, A4[1] - 9.5 * mm, "Compiled 3 Nov 2026")
        canvas.setStrokeColor(GRID)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, A4[1] - 11.5 * mm, A4[0] - MARGIN, A4[1] - 11.5 * mm)
        canvas.line(MARGIN, 12.5 * mm, A4[0] - MARGIN, 12.5 * mm)
        canvas.setFont("DejaVu", 7.6)
        canvas.drawCentredString(A4[0] / 2, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if not isinstance(flowable, Paragraph):
            return
        style = flowable.style.name
        if style not in ("H1", "H2"):
            return
        level = 0 if style == "H1" else 1
        raw = re.sub(r"<[^>]+>", "", flowable.getPlainText())
        label = html.escape(html.unescape(raw), quote=False).strip()
        if not label:
            return
        self._bm += 1
        key = f"bm{self._bm}"
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(label, key, level=level, closed=False)
        self.notify("TOCEntry", (level, label, self.page))


def cover_story(title, subtitle, scope, sections, with_toc):
    story = [Spacer(1, 68 * mm)]
    story.append(Paragraph("READ THIS FIRST", S["CoverKicker"]))
    meta = Table(
        [[Paragraph("<b>Compiled</b>", S["CoverNote"]), Paragraph("3 November 2026", S["CoverNote"])],
         [Paragraph("<b>Coverage</b>", S["CoverNote"]), Paragraph("1 January 2026 → 3 November 2026", S["CoverNote"])],
         [Paragraph("<b>Built for</b>", S["CoverNote"]), Paragraph("UPSC · SSC · Banking · Railways · Defence · State PSC · TET", S["CoverNote"])]],
        colWidths=[32 * mm, AVAIL - 32 * mm],
    )
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), 0.5, GRID),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(meta)
    story.append(Spacer(1, 6 * mm))

    note = Table([[Paragraph(scope, S["CoverNote"])]], colWidths=[AVAIL])
    note.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_AMBER),
        ("LINEBEFORE", (0, 0), (0, 0), 2.4, AMBER),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#f0d9b5")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(note)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph("WHAT'S INSIDE", S["CoverKicker"]))
    rows = [[Paragraph(f"<b>{i}</b>", S["Cell"]), Paragraph(name, S["Cell"])]
            for i, name in sections]
    toc_preview = Table(rows, colWidths=[12 * mm, AVAIL - 12 * mm])
    toc_preview.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, PALE]),
        ("LINEBELOW", (0, 0), (-1, -2), 0.3, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(toc_preview)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "The Markdown files remain the master copy. This PDF replaces decorative emoji with short "
        "text labels and transliterates the Hindi mnemonic phrases into Roman script so every line "
        "prints cleanly; all facts, numbers and source links are unchanged.",
        S["Small"],
    ))
    story.append(NextPageTemplate("normal"))
    story.append(PageBreak())
    if with_toc:
        story.append(Paragraph("CONTENTS", S["TOCTitle"]))
        toc = TableOfContents()
        toc.levelStyles = [S["TOC1"], S["TOC2"]]
        toc.dotsMinLevel = 0
        story.append(toc)
        story.append(PageBreak())
        story.append(Paragraph("", S["Small"]))
    return story


def build(md_path: Path, pdf_path: Path, title, subtitle, banner, scope,
          sections, with_toc=True):
    source = clean_markdown(md_path.read_text(encoding="utf-8"))
    body_html = md.markdown(
        source, extensions=["tables", "sane_lists", "fenced_code"],
        output_format="html5",
    )
    story = cover_story(title, subtitle, scope, sections, with_toc)
    story += html_to_story(body_html)

    doc = GuideDoc(
        str(pdf_path), title, subtitle, banner,
        title=title, author="Arena.ai Agent Mode", subject=subtitle,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=MARGIN, bottomMargin=MARGIN,
    )
    doc.multiBuild(story)
    print(f"Wrote {pdf_path} ({pdf_path.stat().st_size:,} bytes)")


MAIN_SECTIONS = [
    ("1", "Master calendar: January to November 2026"),
    ("2", "Month-wise notes + mnemonics"),
    ("3", "Theme-wise super tables: Slams, cricket, football, medals"),
    ("4", "The mnemonic bank: M1 to M24"),
    ("5", "Trap alerts: where negative marking happens"),
    ("6", "60 rapid-fire one-liners"),
    ("7", "25 practice MCQs with answer key"),
    ("8", "Sources + final revision advice"),
]
CHEAT_SECTIONS = [
    ("1", "Numbers that fetch marks"),
    ("2", "The 24 mnemonics"),
    ("3", "Champion pairs"),
    ("4", "Hosts, mascots, mottos"),
    ("5", "12 trap pairs"),
    ("6", "10-question lightning quiz"),
]

SCOPE = (
    "<b>Scope note:</b> November 2026 is only three days old on the compilation date, "
    "so this guide covers 1 January to 3 November 2026. Events after that date "
    "(Dakar 2026 Youth Olympics through 13 November; Gukesh–Sindarov from 25 November) "
    "are flagged UPCOMING and are not presented as results. Where sources disagree, "
    "the primary/mainstream source is used — always cross-check the latest monthly "
    "capsule before the exam."
)


def main():
    build(
        ROOT / "SPORTS_CURRENT_AFFAIRS_2026.md",
        ROOT / "SPORTS_CURRENT_AFFAIRS_2026.pdf",
        title="SPORTS CURRENT AFFAIRS 2026",
        subtitle="January → November 2026  |  Competitive Exam Guide with Mnemonics",
        banner="Winners · Hosts · Editions · Medal tallies · Awards · Records · 24 original mnemonics",
        scope=SCOPE,
        sections=MAIN_SECTIONS,
        with_toc=True,
    )
    build(
        ROOT / "SPORTS_2026_MNEMONICS.md",
        ROOT / "SPORTS_2026_MNEMONICS.pdf",
        title="SPORTS 2026: MNEMONIC SHEET",
        subtitle="Last-day revision  |  January → November 2026",
        banner="Numbers · M1–M24 · Champion pairs · Hosts/mascots · Trap pairs · Lightning quiz",
        scope=SCOPE,
        sections=CHEAT_SECTIONS,
        with_toc=False,
    )


if __name__ == "__main__":
    main()
