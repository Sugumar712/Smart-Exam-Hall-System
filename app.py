"""
app.py  —  Smart Exam Hall Seating Arrangement System
======================================================
Single-file Flask application.

Run:
    pip install flask pandas openpyxl reportlab
    python app.py

Open: http://127.0.0.1:5000
"""

import io
import re
from string import ascii_uppercase
from datetime import date

import pandas as pd
from flask import Flask, request, jsonify, send_file, render_template_string

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer,
    Table, TableStyle, PageBreak, HRFlowable,
)

app = Flask(__name__)
app.secret_key = "exam-seating-2024"

# ═══════════════════════════════════════════════════════════════════════════
#  SEATING ALGORITHMS
# ═══════════════════════════════════════════════════════════════════════════

def column_letter(index: int) -> str:
    """Zero-based index → Excel-style column letter (A, B … Z, AA …)."""
    letters = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = ascii_uppercase[rem] + letters
    return letters


def parse_register_number(reg: str):
    """
    Parse a register number that may carry a department prefix.
    Accepted: "8001", "AI8001", "CSE8001", "AI-8001", "CSE-8001"
    Returns (prefix, numeric_str).
    """
    reg = reg.strip()
    match = re.fullmatch(r'([A-Za-z]*)[-]?(\d+)', reg)
    if not match:
        raise ValueError(f"Invalid register number format: '{reg}'")
    return match.group(1).upper(), match.group(2)


def generate_register_numbers(start_reg: str, end_reg: str) -> list:
    """Generate all register numbers from start_reg to end_reg inclusive."""
    prefix_s, num_s = parse_register_number(start_reg)
    prefix_e, num_e = parse_register_number(end_reg)

    if prefix_s != prefix_e:
        raise ValueError(
            f"Start/end prefixes don't match: '{prefix_s}' vs '{prefix_e}'"
        )

    start_int, end_int = int(num_s), int(num_e)
    if start_int > end_int:
        raise ValueError(
            f"Start register {start_int} is greater than end {end_int}."
        )

    width = max(len(num_s), len(num_e))
    dash  = "-" if ("-" in start_reg or "-" in end_reg) else ""

    results = []
    for i in range(start_int, end_int + 1):
        numeric_part = str(i).zfill(width)
        results.append(
            f"{prefix_s}{dash}{numeric_part}" if prefix_s else numeric_part
        )
    return results


def build_department_students(departments: list) -> dict:
    """
    Convert list of dept dicts [{Department, Start, End}]
    into {dept_name: [reg_number, …]}.
    """
    dept_students = {}
    for dept in departments:
        name  = dept.get("Department", "").strip()
        start = dept.get("Start", "").strip()
        end   = dept.get("End",   "").strip()
        if not (name and start and end):
            continue
        dept_students[name] = generate_register_numbers(start, end)
    return dept_students


def interleave_departments(dept_students: dict) -> list:
    """Round-robin interleave → [(dept_name, reg_number), …]."""
    result = []
    queues = {k: list(v) for k, v in dept_students.items()}
    while any(queues.values()):
        for dept in list(queues):
            if queues[dept]:
                result.append((dept, queues[dept].pop(0)))
    return result


def split_halls(students: list, capacity: int) -> list:
    """Split interleaved student list into chunks of `capacity`."""
    return [students[i:i + capacity] for i in range(0, len(students), capacity)]


def build_hall_layout(students: list, rows: int, cols: int, arrangement: str):
    """
    Place students into a rows×cols grid.
    arrangement: "Vertical" | "Horizontal" | "Diamond"
    Returns (layout_2d, seat_data_list).
    """
    layout    = [["" for _ in range(cols)] for _ in range(rows)]
    positions = []

    if arrangement == "Horizontal":
        for r in range(rows):
            for c in range(cols):
                positions.append((r, c))

    elif arrangement == "Vertical":
        for c in range(cols):
            for r in range(rows):
                positions.append((r, c))

    else:  # Diamond
        center_r, center_c = rows // 2, cols // 2
        cells = []
        for r in range(rows):
            for c in range(cols):
                cells.append((abs(r - center_r) + abs(c - center_c), r, c))
        cells.sort()
        positions = [(r, c) for _, r, c in cells]

    seat_data = []
    for student, (r, c) in zip(students, positions):
        dept, reg = student
        cell_label = reg if any(ch.isalpha() for ch in reg) else f"{dept}-{reg}"
        layout[r][c] = cell_label
        seat_data.append({
            "Seat":            f"{column_letter(c)}{r + 1}",
            "Department":      dept,
            "Register Number": cell_label,
        })

    return layout, seat_data


def compute_statistics(halls_data: list) -> dict:
    """Return aggregate stats across all generated halls."""
    total_students = sum(len(h["seat_data"]) for h in halls_data)
    dept_counts    = {}
    for h in halls_data:
        for row in h["seat_data"]:
            d = row["Department"]
            dept_counts[d] = dept_counts.get(d, 0) + 1
    return {
        "total_students": total_students,
        "total_halls":    len(halls_data),
        "dept_counts":    dept_counts,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  PDF GENERATION
# ═══════════════════════════════════════════════════════════════════════════

_NAVY      = colors.HexColor("#1B2A4A")
_SLATE     = colors.HexColor("#3A5080")
_BLUE      = colors.HexColor("#2563EB")
_LIGHT_BLUE= colors.HexColor("#EFF6FF")
_LIGHT_GREY= colors.HexColor("#F8FAFC")
_MID_GREY  = colors.HexColor("#CBD5E1")


def _pdf_styles():
    base = getSampleStyleSheet()
    return {
        "institution": ParagraphStyle(
            "Institution", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10,
            textColor=_SLATE, alignment=TA_CENTER, spaceAfter=2,
        ),
        "main_title": ParagraphStyle(
            "MainTitle", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=18,
            textColor=_NAVY, alignment=TA_CENTER, spaceAfter=4,
        ),
        "hall_heading": ParagraphStyle(
            "HallHeading", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=13,
            textColor=_BLUE, alignment=TA_CENTER, spaceAfter=2,
        ),
        "meta": ParagraphStyle(
            "Meta", parent=base["Normal"],
            fontName="Helvetica", fontSize=9,
            textColor=_SLATE, alignment=TA_CENTER,
        ),
        "section_label": ParagraphStyle(
            "SectionLabel", parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=10,
            textColor=_NAVY, alignment=TA_LEFT,
            spaceBefore=10, spaceAfter=4,
        ),
    }


def _seat_table_style(row_count: int) -> TableStyle:
    cmds = [
        ("BACKGROUND",    (0, 0), (-1,  0), _NAVY),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,  0), 9),
        ("ALIGN",         (0, 0), (-1,  0), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1,  0), 6),
        ("TOPPADDING",    (0, 0), (-1,  0), 6),
        ("FONTNAME",      (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 1), (-1, -1), 8),
        ("ALIGN",         (0, 1), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("GRID",          (0, 0), (-1, -1), 0.4, _MID_GREY),
        ("LINEBELOW",     (0, 0), (-1,  0), 1.2, _BLUE),
    ]
    for row in range(1, row_count + 1):
        bg = _LIGHT_BLUE if row % 2 == 0 else _LIGHT_GREY
        cmds.append(("BACKGROUND", (0, row), (-1, row), bg))
    return TableStyle(cmds)


def _layout_table_style() -> TableStyle:
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1,  0), _NAVY),
        ("TEXTCOLOR",     (0, 0), (-1,  0), colors.white),
        ("FONTNAME",      (0, 0), (-1,  0), "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1,  0), 8),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND",    (0, 1), (0,  -1), _SLATE),
        ("TEXTCOLOR",     (0, 1), (0,  -1), colors.white),
        ("FONTNAME",      (0, 1), (0,  -1), "Helvetica-Bold"),
        ("FONTNAME",      (1, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE",      (1, 1), (-1, -1), 7),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.4, _MID_GREY),
        ("LINEBELOW",     (0, 0), (-1,  0), 1.2, _BLUE),
        ("BOX",           (0, 0), (-1, -1), 1,   _SLATE),
    ])


def create_pdf(halls_data: list, exam_title: str = "Examination") -> bytes:
    """Build a complete landscape-A4 PDF for all halls. Returns raw bytes."""
    buffer = io.BytesIO()
    styles = _pdf_styles()
    today  = date.today().strftime("%d %B %Y")

    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
        title=f"{exam_title} – Seating Arrangement",
    )

    elements = []

    for idx, hall in enumerate(halls_data):
        label      = hall["label"]
        seat_data  = hall["seat_data"]
        layout     = hall["layout"]
        col_headers= hall.get("columns", [])

        # Header
        elements.append(Paragraph("Smart Exam Hall Seating Arrangement System", styles["institution"]))
        elements.append(Paragraph(exam_title, styles["main_title"]))
        elements.append(HRFlowable(width="100%", thickness=1.5, color=_BLUE, spaceAfter=6))
        elements.append(Paragraph(label, styles["hall_heading"]))
        elements.append(Paragraph(f"Date: {today}", styles["meta"]))
        elements.append(Spacer(1, 0.4*cm))

        # Seat allocation table
        elements.append(Paragraph("Seat Allocation", styles["section_label"]))
        if seat_data:
            headers    = ["Seat", "Department", "Register Number"]
            table_data = [headers] + [
                [r["Seat"], r["Department"], r["Register Number"]]
                for r in seat_data
            ]
            CHUNK = 35
            chunks = [table_data[:1] + table_data[i:i+CHUNK]
                      for i in range(1, len(table_data), CHUNK)]
            for chunk in chunks:
                t = Table(chunk, repeatRows=1, hAlign="LEFT")
                t.setStyle(_seat_table_style(len(chunk) - 1))
                elements.append(t)
                elements.append(Spacer(1, 0.2*cm))

        elements.append(Spacer(1, 0.4*cm))

        # Hall layout grid
        elements.append(Paragraph("Hall Layout", styles["section_label"]))
        if layout and col_headers:
            num_cols = len(layout[0])
            lt_data  = [[""] + col_headers]
            for r_idx, row in enumerate(layout):
                lt_data.append([str(r_idx+1)] + [c if c else "—" for c in row])

            col_w  = min((landscape(A4)[0] - 3*cm) / (num_cols + 1), 3.2*cm)
            col_ws = [0.8*cm] + [col_w] * num_cols

            lt = Table(lt_data, colWidths=col_ws, repeatRows=1, hAlign="LEFT")
            lt.setStyle(_layout_table_style())
            elements.append(lt)

        if idx < len(halls_data) - 1:
            elements.append(PageBreak())

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


# ═══════════════════════════════════════════════════════════════════════════
#  EXCEL GENERATION
# ═══════════════════════════════════════════════════════════════════════════

def create_excel(halls_data: list) -> bytes:
    """Build an .xlsx workbook (one sheet per hall). Returns raw bytes."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for hall in halls_data:
            label    = hall["label"][:31]
            seat_df  = pd.DataFrame(hall["seat_data"])
            cols     = hall.get("columns", [])
            layout_df= pd.DataFrame(hall["layout"], columns=cols)

            seat_df.to_excel(writer, sheet_name=label, index=False, startrow=0)
            gap = len(seat_df) + 3
            layout_df.to_excel(writer, sheet_name=label, index=True, startrow=gap)

            ws = writer.sheets[label]
            for col_cells in ws.columns:
                max_len = max(
                    (len(str(c.value)) if c.value else 0) for c in col_cells
                )
                ws.column_dimensions[col_cells[0].column_letter].width = max_len + 4

    buffer.seek(0)
    return buffer.read()


# ═══════════════════════════════════════════════════════════════════════════
#  HTML TEMPLATE  (Bootstrap 5 via CDN, all CSS + JS inline)
# ═══════════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Smart Exam Hall Seating System</title>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"/>
<link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
  rel="stylesheet"/>
<style>
/* ── Tokens ─────────────────────────────────────────────────────── */
:root{
  --navy:#1B2A4A; --navy-light:#243660;
  --blue:#2563EB; --blue-light:#3B82F6; --blue-pale:#EFF6FF;
  --slate:#3A5080;
  --surface:#F8FAFC; --surface-2:#F1F5F9;
  --border:#E2E8F0; --border-dark:#CBD5E1;
  --text:#0F172A; --text-muted:#64748B;
  --success:#16A34A; --danger:#DC2626; --white:#FFFFFF;
  --radius-sm:6px; --radius:12px; --radius-lg:18px;
  --shadow-sm:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.04);
  --shadow:0 4px 16px rgba(0,0,0,.08),0 2px 4px rgba(0,0,0,.04);
  --font-body:'Inter',system-ui,sans-serif;
  --font-mono:'JetBrains Mono','Courier New',monospace;
}
*,*::before,*::after{box-sizing:border-box;}
html{scroll-behavior:smooth;}
body{font-family:var(--font-body);background:var(--surface);color:var(--text);
  line-height:1.6;-webkit-font-smoothing:antialiased;}
code{font-family:var(--font-mono);font-size:.85em;background:var(--blue-pale);
  color:var(--blue);padding:2px 6px;border-radius:var(--radius-sm);}

/* ── Navbar ─────────────────────────────────────────────────────── */
#mainNav{background:var(--navy);border-bottom:1px solid rgba(255,255,255,.06);
  box-shadow:0 2px 16px rgba(0,0,0,.25);height:60px;z-index:1030;}
.brand-icon{display:flex;align-items:center;justify-content:center;
  width:34px;height:34px;background:var(--blue);border-radius:8px;font-size:1.1rem;}
.brand-text{font-size:1.15rem;font-weight:700;letter-spacing:-.3px;color:var(--white);}
.brand-accent{color:var(--blue-light);}
.bg-accent-badge{background:rgba(37,99,235,.25)!important;
  border:1px solid rgba(37,99,235,.4);font-size:.78rem;letter-spacing:.3px;}

/* ── Hero ───────────────────────────────────────────────────────── */
.hero-section{
  background:linear-gradient(135deg,var(--navy) 0%,var(--navy-light) 60%,#1e3a6e 100%);
  color:var(--white);padding:4rem 1rem 3.5rem;position:relative;overflow:hidden;}
.hero-section::after{content:'';position:absolute;inset:0;
  background:radial-gradient(ellipse 60% 80% at 80% 50%,rgba(37,99,235,.18),transparent);
  pointer-events:none;}
.hero-eyebrow{font-size:.8rem;font-weight:600;letter-spacing:1.5px;
  text-transform:uppercase;color:var(--blue-light);margin-bottom:.75rem;}
.hero-title{font-size:clamp(2rem,5vw,3rem);font-weight:700;line-height:1.15;
  letter-spacing:-.5px;margin-bottom:1rem;}
.hero-subtitle{font-size:1.05rem;color:rgba(255,255,255,.72);
  max-width:540px;line-height:1.7;}
.hero-stat-cluster{display:flex;flex-direction:column;gap:.6rem;align-items:flex-end;}
.stat-chip{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.15);
  border-radius:50px;padding:.4rem 1rem;font-size:.82rem;font-weight:500;
  color:rgba(255,255,255,.85);backdrop-filter:blur(8px);}
.btn-primary-brand{background:var(--blue);border:none;color:var(--white);font-weight:600;
  border-radius:var(--radius);padding:.65rem 1.5rem;
  transition:background .2s,transform .15s,box-shadow .2s;}
.btn-primary-brand:hover{background:var(--blue-light);color:var(--white);
  transform:translateY(-1px);box-shadow:0 6px 20px rgba(37,99,235,.4);}

/* ── Section Cards ──────────────────────────────────────────────── */
.section-card{background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-lg);box-shadow:var(--shadow-sm);overflow:hidden;
  transition:box-shadow .2s;}
.section-card:hover{box-shadow:var(--shadow);}
.section-header{display:flex;align-items:flex-start;gap:1rem;
  padding:1.4rem 1.75rem;
  background:linear-gradient(to right,var(--blue-pale),var(--white));
  border-bottom:1px solid var(--border);}
.section-icon{display:flex;align-items:center;justify-content:center;
  width:42px;height:42px;min-width:42px;background:var(--blue);color:var(--white);
  border-radius:var(--radius);font-size:1.2rem;}
.section-title{font-size:1.1rem;font-weight:700;color:var(--navy);
  margin:0 0 .15rem;letter-spacing:-.2px;}
.section-subtitle{font-size:.82rem;color:var(--text-muted);margin:0;}
.section-body{padding:1.75rem;}

/* ── Form controls ──────────────────────────────────────────────── */
.form-label{font-size:.875rem;color:var(--navy);margin-bottom:.4rem;}
.form-control,.form-select{border:1.5px solid var(--border-dark);
  border-radius:var(--radius);font-size:.92rem;color:var(--text);background:var(--white);
  transition:border-color .18s,box-shadow .18s;}
.form-control:focus,.form-select:focus{border-color:var(--blue);
  box-shadow:0 0 0 3px rgba(37,99,235,.15);outline:none;}
.text-accent{color:var(--blue)!important;}
.capacity-display{display:flex;align-items:center;justify-content:center;
  height:50px;background:linear-gradient(135deg,var(--navy),var(--slate));
  color:var(--white);font-size:1rem;font-weight:700;border-radius:var(--radius);
  letter-spacing:.5px;}

/* ── Arrangement Cards ──────────────────────────────────────────── */
.arrangement-card{display:flex;flex-direction:column;align-items:center;
  text-align:center;padding:1.5rem 1rem;border:2px solid var(--border);
  border-radius:var(--radius);background:var(--surface);cursor:pointer;
  transition:border-color .2s,background .2s,box-shadow .2s,transform .15s;
  user-select:none;}
.arrangement-card:hover{border-color:var(--blue-light);background:var(--blue-pale);
  transform:translateY(-2px);box-shadow:var(--shadow-sm);}
.btn-check:checked+.arrangement-card{border-color:var(--blue);
  background:var(--blue-pale);box-shadow:0 0 0 3px rgba(37,99,235,.2);}
.arr-icon{font-size:1.8rem;color:var(--blue);margin-bottom:.6rem;}
.arr-name{font-size:.95rem;font-weight:700;color:var(--navy);margin-bottom:.25rem;}
.arr-desc{font-size:.78rem;color:var(--text-muted);line-height:1.4;}

/* ── Department Rows ────────────────────────────────────────────── */
.dept-row{display:grid;grid-template-columns:1fr 1fr 1fr auto;
  gap:.75rem;align-items:end;padding:1rem 1.25rem;
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);margin-bottom:.75rem;transition:box-shadow .2s;}
.dept-row:hover{box-shadow:var(--shadow-sm);}
@media(max-width:767px){
  .dept-row{grid-template-columns:1fr 1fr;gap:.6rem;}
  .dept-row .dept-remove-col{grid-column:1/-1;justify-self:end;}
}
.dept-row-number{font-size:.7rem;font-weight:700;color:var(--white);
  background:var(--blue);border-radius:50%;width:22px;height:22px;
  display:inline-flex;align-items:center;justify-content:center;margin-bottom:.4rem;}
.btn-remove-dept{display:flex;align-items:center;justify-content:center;
  width:38px;height:38px;border:1.5px solid #FCA5A5;background:#FEF2F2;
  color:var(--danger);border-radius:var(--radius);cursor:pointer;font-size:1rem;
  transition:background .18s,border-color .18s;}
.btn-remove-dept:hover{background:#FEE2E2;border-color:var(--danger);}
.btn-add-dept{display:inline-flex;align-items:center;background:var(--blue-pale);
  color:var(--blue);border:1.5px solid rgba(37,99,235,.25);border-radius:var(--radius);
  padding:.45rem 1rem;font-size:.85rem;font-weight:600;cursor:pointer;white-space:nowrap;
  transition:background .18s,border-color .18s;}
.btn-add-dept:hover{background:#DBEAFE;border-color:var(--blue);}
.dept-empty-state{text-align:center;padding:2.5rem 1rem;}

/* ── Generate Button ────────────────────────────────────────────── */
.btn-generate{background:linear-gradient(135deg,var(--blue),#1D4ED8);color:var(--white);
  border:none;border-radius:50px;padding:1rem 3rem;font-size:1.05rem;font-weight:700;
  letter-spacing:.3px;box-shadow:0 6px 24px rgba(37,99,235,.45);
  transition:transform .18s,box-shadow .18s,background .18s;}
.btn-generate:hover{transform:translateY(-2px);
  box-shadow:0 10px 32px rgba(37,99,235,.55);
  background:linear-gradient(135deg,var(--blue-light),var(--blue));color:var(--white);}
.btn-generate:active{transform:translateY(0);}
.btn-generate:disabled{opacity:.65;transform:none;cursor:not-allowed;}

/* ── Stats Bar ──────────────────────────────────────────────────── */
.stats-bar{display:flex;align-items:center;justify-content:center;
  background:var(--white);border:1px solid var(--border);border-radius:var(--radius-lg);
  box-shadow:var(--shadow-sm);padding:1.25rem 2rem;flex-wrap:wrap;gap:0;}
.stat-item{display:flex;flex-direction:column;align-items:center;padding:0 2rem;}
.stat-value{font-size:1.8rem;font-weight:800;color:var(--blue);
  line-height:1;letter-spacing:-1px;}
.stat-label{font-size:.75rem;font-weight:500;color:var(--text-muted);
  text-transform:uppercase;letter-spacing:.8px;margin-top:.25rem;}
.stat-divider{width:1px;height:40px;background:var(--border);}

/* ── Global Action Bar ──────────────────────────────────────────── */
.global-action-bar{display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:.75rem;background:#F0FDF4;border:1px solid #BBF7D0;
  border-radius:var(--radius);padding:1rem 1.5rem;}
.global-action-label{font-weight:600;font-size:.92rem;color:#15803D;}
.btn-dl-pdf{display:inline-flex;align-items:center;background:#DC2626;
  color:var(--white);border:none;border-radius:var(--radius);
  padding:.5rem 1.1rem;font-size:.85rem;font-weight:600;
  transition:background .18s,transform .15s;}
.btn-dl-pdf:hover{background:#B91C1C;color:var(--white);transform:translateY(-1px);}
.btn-dl-excel{display:inline-flex;align-items:center;background:#16A34A;
  color:var(--white);border:none;border-radius:var(--radius);
  padding:.5rem 1.1rem;font-size:.85rem;font-weight:600;
  transition:background .18s,transform .15s;}
.btn-dl-excel:hover{background:#15803D;color:var(--white);transform:translateY(-1px);}
.btn-print-top{display:inline-flex;align-items:center;background:var(--slate);
  color:var(--white);border:none;border-radius:var(--radius);
  padding:.5rem 1.1rem;font-size:.85rem;font-weight:600;
  transition:background .18s,transform .15s;}
.btn-print-top:hover{background:var(--navy);color:var(--white);transform:translateY(-1px);}

/* ── Hall Result Cards ──────────────────────────────────────────── */
.hall-card{background:var(--white);border:1px solid var(--border);
  border-radius:var(--radius-lg);box-shadow:var(--shadow-sm);
  margin-bottom:2rem;overflow:hidden;}
.hall-card-header{display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:.75rem;padding:1.1rem 1.5rem;
  background:linear-gradient(to right,var(--navy),var(--navy-light));color:var(--white);}
.hall-card-title{font-size:1.05rem;font-weight:700;margin:0;
  display:flex;align-items:center;gap:.5rem;}
.hall-badge{font-size:.72rem;background:rgba(255,255,255,.15);
  border:1px solid rgba(255,255,255,.2);border-radius:50px;
  padding:.2rem .75rem;font-weight:500;}
.hall-card-body{padding:1.5rem;}

/* ── Tables ─────────────────────────────────────────────────────── */
.result-table-wrap{overflow-x:auto;border-radius:var(--radius);
  border:1px solid var(--border);margin-bottom:1.5rem;}
.result-table{width:100%;border-collapse:collapse;font-size:.82rem;
  font-family:var(--font-mono);}
.result-table thead th{background:var(--navy);color:var(--white);font-weight:600;
  padding:.65rem 1rem;text-align:center;white-space:nowrap;
  font-family:var(--font-body);font-size:.78rem;letter-spacing:.4px;text-transform:uppercase;}
.result-table thead th:first-child{text-align:left;}
.result-table tbody tr:nth-child(even){background:var(--blue-pale);}
.result-table tbody tr:nth-child(odd){background:var(--white);}
.result-table tbody tr:hover{background:#DBEAFE;}
.result-table tbody td{padding:.55rem 1rem;text-align:center;
  border-bottom:1px solid var(--border);color:var(--text);}
.result-table tbody td:first-child{text-align:left;}

/* ── Layout Grid ────────────────────────────────────────────────── */
.layout-grid-wrap{overflow-x:auto;border-radius:var(--radius);
  border:1px solid var(--border);}
.layout-table{width:100%;border-collapse:collapse;font-size:.75rem;
  font-family:var(--font-mono);}
.layout-table th{background:var(--navy);color:var(--white);
  font-family:var(--font-body);font-weight:700;font-size:.72rem;
  text-align:center;padding:.5rem .6rem;letter-spacing:.5px;min-width:80px;}
.layout-table th.row-header{background:var(--slate);min-width:32px;}
.layout-table tbody tr:nth-child(even) td{background:var(--blue-pale);}
.layout-table tbody tr:nth-child(odd) td{background:var(--white);}
.layout-table td{padding:.45rem .5rem;text-align:center;border:1px solid var(--border);
  white-space:nowrap;transition:background .15s,transform .15s;color:var(--navy);}
/* Signature: glowing seat-hover — maps directly to the core product output */
.layout-table td.occupied:hover{background:#BFDBFE!important;transform:scale(1.04);
  z-index:2;position:relative;border-color:var(--blue);
  box-shadow:0 2px 8px rgba(37,99,235,.25);cursor:default;}
.layout-table td.empty{color:#CBD5E1;font-style:italic;}
.layout-table td.row-label{background:var(--slate)!important;color:var(--white);
  font-family:var(--font-body);font-weight:700;font-size:.72rem;}

/* ── Result section labels ──────────────────────────────────────── */
.result-section-label{display:flex;align-items:center;gap:.5rem;font-size:.85rem;
  font-weight:700;color:var(--navy);margin-bottom:.75rem;
  text-transform:uppercase;letter-spacing:.6px;}
.result-section-label::after{content:'';flex:1;height:1px;background:var(--border);}

/* ── Alerts ─────────────────────────────────────────────────────── */
.alert-custom{border-radius:var(--radius);border:none;font-weight:500;
  font-size:.9rem;padding:1rem 1.25rem;}

/* ── Footer ─────────────────────────────────────────────────────── */
.site-footer{background:var(--navy);color:rgba(255,255,255,.7);
  font-size:.85rem;border-top:1px solid rgba(255,255,255,.06);}

/* ── Print ──────────────────────────────────────────────────────── */
@media print{
  #mainNav,.hero-section,#formSection,.global-action-bar,
  .stats-bar,.btn-dl-pdf,.btn-dl-excel,.btn-print-top,
  .hall-card-header .btn,.site-footer{display:none!important;}
  body{background:white;}
  .hall-card{break-inside:avoid;box-shadow:none;border:1px solid #ccc;margin-bottom:1.5rem;}
  .hall-card-header{background:#1B2A4A!important;-webkit-print-color-adjust:exact;}
}

/* ── Responsive ─────────────────────────────────────────────────── */
@media(max-width:576px){
  .stats-bar{flex-direction:column;gap:1rem;}
  .stat-divider{width:80%;height:1px;}
  .stat-item{padding:0;}
  .section-header{flex-direction:column;}
  .btn-add-dept{width:100%;justify-content:center;margin-top:.5rem;}
}
</style>
</head>
<body>

<!-- NAVBAR -->
<nav class="navbar navbar-expand-lg navbar-dark sticky-top" id="mainNav">
  <div class="container-fluid px-4">
    <a class="navbar-brand d-flex align-items-center gap-2" href="/">
      <span class="brand-icon"><i class="bi bi-mortarboard-fill"></i></span>
      <span class="brand-text">ExamSeat <span class="brand-accent">Pro</span></span>
    </a>
    <div class="ms-auto d-flex align-items-center gap-3">
      <span class="badge bg-accent-badge text-white px-3 py-2">
        <i class="bi bi-shield-check me-1"></i>Smart Seating System
      </span>
    </div>
  </div>
</nav>

<!-- HERO -->
<header class="hero-section">
  <div class="container py-3">
    <div class="row align-items-center">
      <div class="col-lg-8">
        <p class="hero-eyebrow"><i class="bi bi-grid-3x3-gap-fill me-2"></i>Automated Hall Management</p>
        <h1 class="hero-title">Smart Exam Hall<br>Seating Arrangement</h1>
        <p class="hero-subtitle">
          Generate professional, conflict-free exam seating plans instantly.
          Supports unlimited departments, flexible layouts, and PDF + Excel export.
        </p>
        <div class="d-flex flex-wrap gap-3 mt-4">
          <a href="#formSection" class="btn btn-primary-brand btn-lg">
            <i class="bi bi-pencil-square me-2"></i>Start Configuring
          </a>
        </div>
      </div>
      <div class="col-lg-4 d-none d-lg-flex justify-content-end">
        <div class="hero-stat-cluster">
          <div class="stat-chip"><i class="bi bi-buildings me-1"></i>Multi-Hall</div>
          <div class="stat-chip"><i class="bi bi-diagram-3 me-1"></i>Round-Robin</div>
          <div class="stat-chip"><i class="bi bi-file-earmark-pdf me-1"></i>PDF Export</div>
          <div class="stat-chip"><i class="bi bi-file-earmark-excel me-1"></i>Excel Export</div>
        </div>
      </div>
    </div>
  </div>
</header>

<!-- MAIN -->
<main class="container-xl py-5 px-3 px-md-4" id="formSection">

  <div id="alertPlaceholder"></div>

  <form id="seatingForm" novalidate>

    <!-- HALL DETAILS -->
    <div class="section-card mb-4">
      <div class="section-header">
        <span class="section-icon"><i class="bi bi-building"></i></span>
        <div>
          <h2 class="section-title">Hall Details</h2>
          <p class="section-subtitle">Configure the exam hall dimensions and capacity</p>
        </div>
      </div>
      <div class="section-body">
        <div class="row g-4">

          <div class="col-md-6">
            <label class="form-label fw-semibold" for="exam_title">
              <i class="bi bi-journal-text me-1 text-accent"></i>Examination Title
            </label>
            <input type="text" class="form-control form-control-lg" id="exam_title"
                   name="exam_title" value="End Semester Examination"
                   placeholder="e.g. End Semester Examination"/>
            <div class="form-text">Appears in the PDF header.</div>
          </div>

          <div class="col-md-6">
            <label class="form-label fw-semibold" for="hall_name">
              <i class="bi bi-building me-1 text-accent"></i>Hall Name / Prefix
            </label>
            <input type="text" class="form-control form-control-lg" id="hall_name"
                   name="hall_name" value="Hall"
                   placeholder="e.g. Main Hall, Lab Block" required/>
            <div class="invalid-feedback">Hall name is required.</div>
          </div>

          <div class="col-sm-6 col-lg-3">
            <label class="form-label fw-semibold" for="students_per_hall">
              <i class="bi bi-people me-1 text-accent"></i>Students Per Hall
            </label>
            <input type="number" class="form-control form-control-lg" id="students_per_hall"
                   name="students_per_hall" value="30" min="1" required/>
            <div class="invalid-feedback">Must be at least 1.</div>
          </div>

          <div class="col-sm-6 col-lg-3">
            <label class="form-label fw-semibold" for="number_of_rows">
              <i class="bi bi-layout-three-columns me-1 text-accent"></i>Number of Rows
            </label>
            <input type="number" class="form-control form-control-lg" id="number_of_rows"
                   name="number_of_rows" value="6" min="1" required/>
            <div class="invalid-feedback">Must be at least 1.</div>
          </div>

          <div class="col-sm-6 col-lg-3">
            <label class="form-label fw-semibold" for="number_of_columns">
              <i class="bi bi-layout-three-columns me-1 text-accent"></i>Number of Columns
            </label>
            <input type="number" class="form-control form-control-lg" id="number_of_columns"
                   name="number_of_columns" value="5" min="1" required/>
            <div class="invalid-feedback">Must be at least 1.</div>
          </div>

          <div class="col-sm-6 col-lg-3">
            <label class="form-label fw-semibold">
              <i class="bi bi-calculator me-1 text-accent"></i>Total Capacity
            </label>
            <div class="capacity-display" id="capacityDisplay">30 seats</div>
          </div>

        </div>
      </div>
    </div>

    <!-- ARRANGEMENT -->
    <div class="section-card mb-4">
      <div class="section-header">
        <span class="section-icon"><i class="bi bi-grid-3x3"></i></span>
        <div>
          <h2 class="section-title">Arrangement Type</h2>
          <p class="section-subtitle">Choose how students are assigned to seats</p>
        </div>
      </div>
      <div class="section-body">
        <div class="row g-3">
          <div class="col-md-4">
            <input type="radio" class="btn-check" name="arrangement"
                   id="arr_vertical" value="Vertical" checked/>
            <label class="arrangement-card w-100" for="arr_vertical">
              <div class="arr-icon"><i class="bi bi-arrow-down-up"></i></div>
              <div class="arr-name">Vertical</div>
              <div class="arr-desc">Fill columns top-to-bottom, left-to-right</div>
            </label>
          </div>
          <div class="col-md-4">
            <input type="radio" class="btn-check" name="arrangement"
                   id="arr_horizontal" value="Horizontal"/>
            <label class="arrangement-card w-100" for="arr_horizontal">
              <div class="arr-icon"><i class="bi bi-arrow-left-right"></i></div>
              <div class="arr-name">Horizontal</div>
              <div class="arr-desc">Fill rows left-to-right, top-to-bottom</div>
            </label>
          </div>
          <div class="col-md-4">
            <input type="radio" class="btn-check" name="arrangement"
                   id="arr_diamond" value="Diamond"/>
            <label class="arrangement-card w-100" for="arr_diamond">
              <div class="arr-icon"><i class="bi bi-diamond"></i></div>
              <div class="arr-name">Diamond</div>
              <div class="arr-desc">Fill from centre outward in a diamond pattern</div>
            </label>
          </div>
        </div>
      </div>
    </div>

    <!-- DEPARTMENTS -->
    <div class="section-card mb-4">
      <div class="section-header">
        <span class="section-icon"><i class="bi bi-person-badge"></i></span>
        <div>
          <h2 class="section-title">Department Details</h2>
          <p class="section-subtitle">
            Add one or more departments. Register numbers support formats like
            <code>8001</code>, <code>AI8001</code>, <code>CSE-8001</code>.
          </p>
        </div>
        <button type="button" class="btn-add-dept ms-auto" id="addDeptBtn">
          <i class="bi bi-plus-circle me-2"></i>Add Department
        </button>
      </div>
      <div class="section-body">
        <div id="departmentList"></div>
        <div class="dept-empty-state" id="deptEmptyState" style="display:none">
          <i class="bi bi-inbox display-6 text-muted"></i>
          <p class="mt-2 text-muted">No departments added yet.</p>
        </div>
      </div>
    </div>

    <!-- GENERATE -->
    <div class="d-flex justify-content-center mt-2 mb-5">
      <button type="submit" class="btn btn-generate" id="generateBtn">
        <span class="btn-generate-inner">
          <i class="bi bi-lightning-charge-fill me-2"></i>Generate Seating Arrangement
        </span>
        <span class="btn-spinner d-none">
          <span class="spinner-border spinner-border-sm me-2"></span>Generating…
        </span>
      </button>
    </div>

  </form>

  <!-- RESULTS -->
  <section id="resultsSection" style="display:none">

    <!-- Stats -->
    <div class="stats-bar mb-4">
      <div class="stat-item">
        <span class="stat-value" id="statTotalStudents">—</span>
        <span class="stat-label">Total Students</span>
      </div>
      <div class="stat-divider"></div>
      <div class="stat-item">
        <span class="stat-value" id="statTotalHalls">—</span>
        <span class="stat-label">Halls Generated</span>
      </div>
      <div class="stat-divider"></div>
      <div class="stat-item">
        <span class="stat-value" id="statDepts">—</span>
        <span class="stat-label">Departments</span>
      </div>
    </div>

    <!-- Global downloads -->
    <div class="global-action-bar mb-4">
      <span class="global-action-label">
        <i class="bi bi-check-circle-fill text-success me-2"></i>
        Seating arrangement generated successfully
      </span>
      <div class="d-flex gap-2 flex-wrap">
        <button class="btn-dl-pdf" id="globalPdfBtn">
          <i class="bi bi-file-earmark-pdf me-2"></i>Download All PDF
        </button>
        <button class="btn-dl-excel" id="globalExcelBtn">
          <i class="bi bi-file-earmark-excel me-2"></i>Download All Excel
        </button>
        <button class="btn-print-top" onclick="window.print()">
          <i class="bi bi-printer me-2"></i>Print
        </button>
      </div>
    </div>

    <!-- Hall cards -->
    <div id="hallResults"></div>

  </section>

</main>

<!-- FOOTER -->
<footer class="site-footer mt-5">
  <div class="container text-center py-4">
    <p class="mb-1 fw-semibold">Smart Exam Hall Seating Arrangement System</p>
    <p class="text-muted small mb-0">
      Automated seating plans &mdash; round-robin distribution &amp; multi-format export.
    </p>
  </div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>
"use strict";

/* ── State ──────────────────────────────────────────────────────── */
let generatedHalls = [];
let lastExamTitle  = "";
let deptCounter    = 0;

/* ── DOM refs (resolved after DOMContentLoaded) ─────────────────── */
let departmentList, deptEmptyState, alertPlaceholder,
    seatingForm, generateBtn, resultsSection, hallResults,
    statTotalStudents, statTotalHalls, statDepts,
    globalPdfBtn, globalExcelBtn,
    rowsInput, colsInput, capacityDisplay;

/* ── Department row factory ─────────────────────────────────────── */
function createDeptRow() {
  deptCounter++;
  const idx  = deptCounter;
  const wrap = document.createElement("div");
  wrap.className  = "dept-row";
  wrap.dataset.id = idx;
  wrap.innerHTML  = `
    <div>
      <label class="form-label fw-semibold d-flex align-items-center gap-2">
        <span class="dept-row-number">${idx}</span>Department Name
      </label>
      <input type="text" class="form-control" name="dept_name[]"
             placeholder="e.g. CSE, AI, ECE" required/>
    </div>
    <div>
      <label class="form-label fw-semibold">
        <i class="bi bi-123 me-1 text-accent"></i>From Register No.
      </label>
      <input type="text" class="form-control" name="start_reg[]"
             placeholder="e.g. AI-8001 or 8001" required/>
    </div>
    <div>
      <label class="form-label fw-semibold">
        <i class="bi bi-123 me-1 text-accent"></i>To Register No.
      </label>
      <input type="text" class="form-control" name="end_reg[]"
             placeholder="e.g. AI-8060 or 8060" required/>
    </div>
    <div class="dept-remove-col">
      <label class="form-label fw-semibold" style="visibility:hidden">X</label>
      <button type="button" class="btn-remove-dept" title="Remove">
        <i class="bi bi-trash3"></i>
      </button>
    </div>`;
  wrap.querySelector(".btn-remove-dept").addEventListener("click", () => {
    wrap.remove();
    toggleEmpty();
  });
  return wrap;
}

function addDept() {
  departmentList.appendChild(createDeptRow());
  toggleEmpty();
}

function toggleEmpty() {
  deptEmptyState.style.display =
    departmentList.children.length === 0 ? "block" : "none";
}

/* ── Capacity display ───────────────────────────────────────────── */
function updateCapacity() {
  const r = parseInt(rowsInput.value, 10) || 0;
  const c = parseInt(colsInput.value, 10) || 0;
  capacityDisplay.textContent = (r * c) > 0 ? `${r * c} seats` : "—";
}

/* ── Alert helpers ──────────────────────────────────────────────── */
function showAlert(msg, type = "danger") {
  alertPlaceholder.innerHTML = `
    <div class="alert alert-${type} alert-custom alert-dismissible fade show mb-4" role="alert">
      <i class="bi bi-${type==='danger'?'exclamation-triangle':'check-circle'}-fill me-2"></i>
      ${esc(msg)}
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    </div>`;
  alertPlaceholder.scrollIntoView({ behavior:"smooth", block:"start" });
}
function clearAlert() { alertPlaceholder.innerHTML = ""; }

/* ── Form submit ────────────────────────────────────────────────── */
async function handleSubmit(e) {
  e.preventDefault();
  clearAlert();
  if (!seatingForm.checkValidity()) {
    seatingForm.classList.add("was-validated");
    showAlert("Please fill in all required fields.");
    return;
  }
  setBusy(true);
  try {
    const res  = await fetch("/generate", { method:"POST", body: new FormData(seatingForm) });
    const data = await res.json();
    if (!res.ok || !data.success) { showAlert(data.error || "Unexpected error."); setBusy(false); return; }
    generatedHalls = data.halls;
    lastExamTitle  = document.getElementById("exam_title").value || "End Semester Examination";
    renderResults(data.halls, data.stats);
  } catch (err) {
    showAlert("Network error: " + err.message);
  }
  setBusy(false);
}

function setBusy(on) {
  generateBtn.disabled = on;
  generateBtn.querySelector(".btn-generate-inner").classList.toggle("d-none", on);
  generateBtn.querySelector(".btn-spinner").classList.toggle("d-none", !on);
}

/* ── Render results ─────────────────────────────────────────────── */
function renderResults(halls, stats) {
  statTotalStudents.textContent = stats.total_students;
  statTotalHalls.textContent    = stats.total_halls;
  statDepts.textContent         = Object.keys(stats.dept_counts).length;
  hallResults.innerHTML         = "";
  halls.forEach(h => hallResults.appendChild(buildHallCard(h)));
  resultsSection.style.display  = "block";
  resultsSection.scrollIntoView({ behavior:"smooth", block:"start" });
}

function buildHallCard(hall) {
  const card = document.createElement("div");
  card.className = "hall-card";
  card.innerHTML = `
    <div class="hall-card-header">
      <h3 class="hall-card-title">
        <i class="bi bi-building"></i>${esc(hall.label)}
        <span class="hall-badge">${hall.seat_data.length} students</span>
      </h3>
      <div class="d-flex gap-2 flex-wrap">
        <button class="btn btn-sm btn-dl-pdf hall-pdf-btn">
          <i class="bi bi-file-earmark-pdf me-1"></i>PDF
        </button>
        <button class="btn btn-sm btn-dl-excel hall-excel-btn">
          <i class="bi bi-file-earmark-excel me-1"></i>Excel
        </button>
      </div>
    </div>
    <div class="hall-card-body">
      <p class="result-section-label"><i class="bi bi-table me-1"></i>Seat Allocation</p>
      <div class="result-table-wrap mb-4">${buildSeatTable(hall.seat_data)}</div>
      <p class="result-section-label"><i class="bi bi-grid-3x3 me-1"></i>Hall Layout</p>
      <div class="layout-grid-wrap">${buildLayoutTable(hall.layout, hall.columns)}</div>
    </div>`;
  card.querySelector(".hall-pdf-btn").addEventListener("click", () =>
    dlFile("/download/pdf",   { halls:[hall], exam_title:lastExamTitle }, `${hall.label}.pdf`));
  card.querySelector(".hall-excel-btn").addEventListener("click", () =>
    dlFile("/download/excel", { halls:[hall] }, `${hall.label}.xlsx`));
  return card;
}

function buildSeatTable(data) {
  if (!data || !data.length) return '<p class="text-muted small">No data.</p>';
  const rows = data.map(r =>
    `<tr><td>${esc(r.Seat)}</td><td>${esc(r.Department)}</td><td>${esc(r["Register Number"])}</td></tr>`
  ).join("");
  return `<table class="result-table">
    <thead><tr><th>Seat</th><th>Department</th><th>Register Number</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function buildLayoutTable(layout, columns) {
  if (!layout || !layout.length) return '<p class="text-muted small">No data.</p>';
  const heads = columns.map(c => `<th>${esc(c)}</th>`).join("");
  const bodyRows = layout.map((row, ri) => {
    const cells = row.map(cell => {
      const empty = !cell || !cell.trim();
      return `<td class="${empty?'empty':'occupied'}">${esc(empty?"—":cell)}</td>`;
    }).join("");
    return `<tr><td class="row-label">${ri+1}</td>${cells}</tr>`;
  }).join("");
  return `<table class="layout-table">
    <thead><tr><th class="row-header">#</th>${heads}</tr></thead>
    <tbody>${bodyRows}</tbody></table>`;
}

/* ── Download helper ────────────────────────────────────────────── */
async function dlFile(url, payload, filename) {
  try {
    const res = await fetch(url, {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body: JSON.stringify(payload),
    });
    if (!res.ok) { const e = await res.json(); showAlert(e.error||"Download failed."); return; }
    const blob = await res.blob();
    const a    = document.createElement("a");
    a.href     = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
  } catch(err) { showAlert("Download error: " + err.message); }
}

/* ── Security ───────────────────────────────────────────────────── */
function esc(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g,"&quot;").replace(/'/g,"&#039;");
}

/* ── Init ───────────────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", () => {
  departmentList    = document.getElementById("departmentList");
  deptEmptyState    = document.getElementById("deptEmptyState");
  alertPlaceholder  = document.getElementById("alertPlaceholder");
  seatingForm       = document.getElementById("seatingForm");
  generateBtn       = document.getElementById("generateBtn");
  resultsSection    = document.getElementById("resultsSection");
  hallResults       = document.getElementById("hallResults");
  statTotalStudents = document.getElementById("statTotalStudents");
  statTotalHalls    = document.getElementById("statTotalHalls");
  statDepts         = document.getElementById("statDepts");
  globalPdfBtn      = document.getElementById("globalPdfBtn");
  globalExcelBtn    = document.getElementById("globalExcelBtn");
  rowsInput         = document.getElementById("number_of_rows");
  colsInput         = document.getElementById("number_of_columns");
  capacityDisplay   = document.getElementById("capacityDisplay");

  addDept(); addDept();  // start with 2 departments
  document.getElementById("addDeptBtn").addEventListener("click", addDept);
  rowsInput.addEventListener("input", updateCapacity);
  colsInput.addEventListener("input", updateCapacity);
  updateCapacity();
  seatingForm.addEventListener("submit", handleSubmit);
  globalPdfBtn.addEventListener("click", () => {
    if (generatedHalls.length)
      dlFile("/download/pdf", { halls:generatedHalls, exam_title:lastExamTitle },
             "Seating_Arrangement.pdf");
  });
  globalExcelBtn.addEventListener("click", () => {
    if (generatedHalls.length)
      dlFile("/download/excel", { halls:generatedHalls }, "Seating_Arrangement.xlsx");
  });
});
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════
#  FLASK ROUTES
# ═══════════════════════════════════════════════════════════════════════════

def _parse_form(form) -> dict:
    """Parse and validate the POST form. Returns a params dict or raises ValueError."""
    hall_name   = form.get("hall_name",   "Hall").strip()  or "Hall"
    exam_title  = form.get("exam_title",  "End Semester Examination").strip() \
                  or "End Semester Examination"

    try:
        students_per_hall = int(form.get("students_per_hall", 30))
        rows              = int(form.get("number_of_rows",    6))
        cols              = int(form.get("number_of_columns", 5))
    except (ValueError, TypeError):
        raise ValueError("Students per hall, rows, and columns must be whole numbers.")

    if students_per_hall < 1:
        raise ValueError("Students per hall must be at least 1.")
    if rows < 1 or cols < 1:
        raise ValueError("Rows and columns must each be at least 1.")

    arrangement = form.get("arrangement", "Vertical")
    if arrangement not in ("Vertical", "Horizontal", "Diamond"):
        arrangement = "Vertical"

    dept_names = form.getlist("dept_name[]")
    start_regs = form.getlist("start_reg[]")
    end_regs   = form.getlist("end_reg[]")

    departments = [
        {"Department": n.strip(), "Start": s.strip(), "End": e.strip()}
        for n, s, e in zip(dept_names, start_regs, end_regs)
    ]

    return {
        "hall_name":         hall_name,
        "exam_title":        exam_title,
        "students_per_hall": students_per_hall,
        "rows":              rows,
        "cols":              cols,
        "arrangement":       arrangement,
        "departments":       departments,
    }


def _run_pipeline(params: dict) -> list:
    """Execute the full seating pipeline. Returns halls_data list."""
    dept_students = build_department_students(params["departments"])

    if not dept_students:
        raise ValueError(
            "No valid departments found. "
            "Please fill in at least one complete department row."
        )

    students = interleave_departments(dept_students)
    halls    = split_halls(students, params["students_per_hall"])
    capacity = params["rows"] * params["cols"]
    halls_data = []

    for index, hall_students in enumerate(halls):
        if len(hall_students) > capacity:
            raise ValueError(
                f"Hall {index + 1} has {len(hall_students)} students but only "
                f"{capacity} seats ({params['rows']} rows × {params['cols']} cols). "
                "Increase rows/columns or reduce students per hall."
            )
        label      = f"{params['hall_name']} {column_letter(index)}"
        layout, seat_data = build_hall_layout(
            hall_students, params["rows"], params["cols"], params["arrangement"]
        )
        col_headers = [column_letter(i) for i in range(params["cols"])]
        halls_data.append({
            "label":     label,
            "seat_data": seat_data,
            "layout":    layout,
            "columns":   col_headers,
        })

    return halls_data


@app.route("/", methods=["GET"])
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/generate", methods=["POST"])
def generate():
    try:
        params     = _parse_form(request.form)
        halls_data = _run_pipeline(params)
        stats      = compute_statistics(halls_data)
        return jsonify({"success": True, "halls": halls_data, "stats": stats})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": f"Unexpected error: {exc}"}), 500


@app.route("/download/pdf", methods=["POST"])
def download_pdf():
    try:
        data       = request.get_json(force=True)
        halls_data = data.get("halls", [])
        exam_title = data.get("exam_title", "End Semester Examination")
        if not halls_data:
            return jsonify({"error": "No halls data provided."}), 400
        pdf_bytes = create_pdf(halls_data, exam_title=exam_title)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="Seating_Arrangement.pdf",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/download/excel", methods=["POST"])
def download_excel():
    try:
        data       = request.get_json(force=True)
        halls_data = data.get("halls", [])
        if not halls_data:
            return jsonify({"error": "No halls data provided."}), 400
        xl_bytes = create_excel(halls_data)
        return send_file(
            io.BytesIO(xl_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="Seating_Arrangement.xlsx",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# ═══════════════════════════════════════════════════════════════════════════
import os

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )