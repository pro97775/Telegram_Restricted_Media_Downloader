import re
import textwrap
from html import escape
from pathlib import Path
from xml.sax.saxutils import unescape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parent
PAGE_WIDTH, _ = A4
LEFT = RIGHT = 16 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT - RIGHT


def register_fonts():
    candidates = [
        (
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("C:/Windows/Fonts/ariali.ttf"),
            Path("C:/Windows/Fonts/arialbi.ttf"),
        ),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf")),
    ]
    for regular, bold, italic, bold_italic in candidates:
        if all(font.exists() for font in (regular, bold, italic, bold_italic)):
            pdfmetrics.registerFont(TTFont("TRMD", str(regular)))
            pdfmetrics.registerFont(TTFont("TRMD-Bold", str(bold)))
            pdfmetrics.registerFont(TTFont("TRMD-Italic", str(italic)))
            pdfmetrics.registerFont(TTFont("TRMD-BoldItalic", str(bold_italic)))
            pdfmetrics.registerFontFamily(
                "TRMD", normal="TRMD", bold="TRMD-Bold",
                italic="TRMD-Italic", boldItalic="TRMD-BoldItalic",
            )
            return "TRMD", "TRMD-Bold"
    return "Helvetica", "Helvetica-Bold"


FONT, BOLD = register_fonts()
CODE_FONT = "Courier"


def styles_for(title):
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "DocTitle", parent=styles["Title"], fontName=BOLD, fontSize=22,
        leading=28, textColor=colors.HexColor("#17324d"), spaceAfter=12,
    ))
    styles.add(ParagraphStyle(
        "DocH1", parent=styles["Heading1"], fontName=BOLD, fontSize=16,
        leading=20, textColor=colors.HexColor("#17324d"), spaceBefore=12,
        spaceAfter=6, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        "DocH2", parent=styles["Heading2"], fontName=BOLD, fontSize=12,
        leading=16, textColor=colors.HexColor("#245b82"), spaceBefore=9,
        spaceAfter=4, keepWithNext=True,
    ))
    styles.add(ParagraphStyle(
        "DocBody", parent=styles["BodyText"], fontName=FONT, fontSize=9.2,
        leading=13, alignment=TA_LEFT, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        "DocNote", parent=styles["BodyText"], fontName=FONT, fontSize=8,
        leading=11, textColor=colors.HexColor("#555555"), spaceAfter=10,
    ))
    styles.add(ParagraphStyle(
        "DocCode", parent=styles["Code"], fontName=CODE_FONT, fontSize=7.4,
        leading=9, leftIndent=7, rightIndent=7, backColor=colors.HexColor("#f1f4f7"),
        borderPadding=5, spaceBefore=2, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        "DocTable", parent=styles["BodyText"], fontName=FONT, fontSize=7.3,
        leading=9.5,
    ))
    return styles


def inline_markup(value):
    value = value.replace("🤖", "Bot required")
    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    links = []

    def save_link(match):
        label, url = match.groups()
        if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url):
            return label
        links.append((label, url))
        return f"@@LINK{len(links) - 1}@@"

    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", save_link, value)
    value = re.sub(r"<[^>]+>", "", value)
    value = escape(unescape(value))
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", value)
    for index, (label, url) in enumerate(links):
        safe_label = escape(unescape(label))
        safe_url = escape(unescape(url), {"\"": "&quot;"})
        value = value.replace(
            f"@@LINK{index}@@",
            f'<link href="{safe_url}" color="#1769aa">{safe_label}</link>',
        )
    return value


def table_cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(FONT, 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(PAGE_WIDTH - RIGHT, 9 * mm, str(doc.page))
    canvas.restoreState()


def build(markdown_path, output_path, title, include_image_note=False):
    styles = styles_for(title)
    lines = markdown_path.read_text(encoding="utf-8").splitlines()
    story = [Paragraph(escape(title), styles["DocTitle"])]
    if include_image_note:
        story.append(Paragraph(
            "English text edition. Embedded screenshots and image-only labels are omitted; follow the translated written steps.",
            styles["DocNote"],
        ))

    in_code = False
    code_lines = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        i += 1
        if line.startswith("```"):
            if in_code:
                wrapped = []
                for code_line in code_lines:
                    wrapped.extend(textwrap.wrap(code_line, width=92, subsequent_indent="    ") or [""])
                story.append(Preformatted("\n".join(wrapped), styles["DocCode"]))
                code_lines = []
                in_code = False
            else:
                in_code = True
            continue
        if in_code:
            code_lines.append(raw)
            continue
        if not line or line in ("---", "***"):
            story.append(Spacer(1, 3))
            continue
        if re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", line):
            continue
        if line.startswith("|"):
            table_rows = []
            while i <= len(lines) and lines[i - 1].strip().startswith("|"):
                row_line = lines[i - 1].strip()
                i += 1
                cells = table_cells(row_line)
                if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                    continue
                table_rows.append([Paragraph(inline_markup(cell), styles["DocTable"]) for cell in cells])
            if table_rows:
                columns = max(len(row) for row in table_rows)
                for row in table_rows:
                    row.extend([Paragraph("", styles["DocTable"])] * (columns - len(row)))
                widths = [CONTENT_WIDTH / columns] * columns
                table = Table(table_rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
                table.setStyle(TableStyle([
                    ("FONTNAME", (0, 0), (-1, -1), FONT),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7edf3")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17324d")),
                    ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c7d0d9")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(table)
                story.append(Spacer(1, 5))
            continue
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            text = line[level:].strip()
            if level == 1 and text == title:
                continue
            story.append(Paragraph(inline_markup(text), styles["DocH1" if level <= 2 else "DocH2"]))
            continue
        if line.startswith(">"):
            line = line.lstrip("> ")
            admonition = re.match(r"^\[!(Tip|Important)\]\s*", line, re.IGNORECASE)
            if admonition:
                line = f"{admonition.group(1).capitalize()}: {line[admonition.end():]}"
        if line.startswith(("- ", "* ")):
            line = "• " + line[2:]
        elif re.match(r"\d+\.\s", line):
            line = re.sub(r"^(\d+\.)\s+", r"\1  ", line)
        if line.startswith("<") and ("<img" in line or line.startswith("<p")):
            continue
        story.append(Paragraph(inline_markup(line), styles["DocBody"]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output_path), pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT,
        topMargin=16 * mm, bottomMargin=16 * mm, title=title, author="TRMD",
    )
    document.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    build(ROOT / "README.md", ROOT / "res" / "User_Guide.pdf", "TRMD User Guide", True)
    build(ROOT / "README.md", ROOT / "res" / "使用必读.pdf", "TRMD User Guide", True)
    build(ROOT / "docs" / "FAQ.md", ROOT / "res" / "FAQ.pdf", "TRMD Frequently Asked Questions")
    build(ROOT / "docs" / "FAQ.md", ROOT / "res" / "Wiki.pdf", "TRMD Frequently Asked Questions")
