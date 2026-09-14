"""
Smart Exam Hall Seating Arrangement System - Advanced College Edition
Deterministic College Seating Order Generator with 1 or 2 Students Per Bench.
"""

import io
import os
import re
from datetime import datetime
from string import ascii_uppercase

import pandas as pd
from flask import Flask, jsonify, render_template_string, request, send_file

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "smart-exam-hall-college-key")


# ---------------------------------------------------------------------------
# Helper Algorithms
# ---------------------------------------------------------------------------

def column_letter(index: int) -> str:
    """Converts 0-based column index to letter: 0->A, 1->B, 25->Z, 26->AA."""
    letters = ""
    index += 1
    while index > 0:
        index, rem = divmod(index - 1, 26)
        letters = ascii_uppercase[rem] + letters
    return letters


def parse_register_number(reg: str):
    """Extracts non-numeric prefix and numeric digits."""
    reg = str(reg).strip()
    match = re.fullmatch(r"([A-Za-z0-9_\-]*?)([0-9]+)", reg)
    if not match:
        raise ValueError(f"Invalid register number format: '{reg}'. Must end with digits.")
    return match.group(1), match.group(2), int(match.group(2))


def generate_register_numbers(start_reg: str, end_reg: str):
    """Generates inclusive range of register numbers."""
    prefix_s, num_s, start_int = parse_register_number(start_reg)
    prefix_e, num_e, end_int = parse_register_number(end_reg)

    if prefix_s != prefix_e:
        raise ValueError(
            f"Prefixes do not match: '{prefix_s}' vs '{prefix_e}'"
        )
    if start_int > end_int:
        raise ValueError(
            f"Start register ({start_int}) cannot be greater than end register ({end_int})."
        )

    width = max(len(num_s), len(num_e))
    return [f"{prefix_s}{str(i).zfill(width)}" for i in range(start_int, end_int + 1)]


def build_department_students(departments):
    """Builds mapping of department name -> list of register numbers with strict validation."""
    result = {}
    seen_names = set()
    seen_regs = set()

    for item in (departments or []):
        if isinstance(item, dict):
            name = str(item.get("Department", "")).strip()
            start = str(item.get("Start", "")).strip()
            end = str(item.get("End", "")).strip()
        elif isinstance(item, (list, tuple)) and len(item) >= 3:
            name, start, end = str(item[0]).strip(), str(item[1]).strip(), str(item[2]).strip()
        else:
            continue

        if not name:
            raise ValueError("Department name cannot be empty.")
        if not (start and end):
            raise ValueError(f"Department '{name}' requires both start and end register numbers.")

        key = name.casefold()
        if key in seen_names:
            raise ValueError(f"Duplicate department name detected: '{name}'.")
        seen_names.add(key)

        regs = generate_register_numbers(start, end)
        for r in regs:
            if r in seen_regs:
                raise ValueError(f"Duplicate register number detected across departments: '{r}'.")
            seen_regs.add(r)

        result[name] = regs

    return result


def make_benches(dept_students, max_benches, students_per_bench=2):
    """
    Deterministic seating allocation:
    - If students_per_bench == 1:
      Every bench has 1 student (Student 2 is None).
    - If students_per_bench == 2:
      Primary 2 departments are paired first (benches 1..N).
      When one runs out, subsequent departments fill remaining empty bench positions.
      Never allow 3 students on a bench.
    """
    depts = list(dept_students.keys())
    queues = {d: list(dept_students[d]) for d in depts}
    benches = []

    if students_per_bench == 1:
        for d in depts:
            while queues[d] and len(benches) < max_benches:
                benches.append([(d, queues[d].pop(0)), None])
        return benches

    # 2 Students Per Bench:
    primary = depts[:2]
    remaining_depts = depts[2:]

    while any(queues[d] for d in primary) and len(benches) < max_benches:
        left = (primary[0], queues[primary[0]].pop(0)) if queues[primary[0]] else None
        right = (primary[1], queues[primary[1]].pop(0)) if len(primary) > 1 and queues[primary[1]] else None

        # If one department runs out, use remaining empty bench positions for next department
        if left is not None and right is None:
            for d in remaining_depts:
                if queues[d]:
                    right = (d, queues[d].pop(0))
                    break
        elif left is None and right is not None:
            for d in remaining_depts:
                if queues[d]:
                    left = (d, queues[d].pop(0))
                    break

        if left is not None or right is not None:
            benches.append([left, right])

    # Leftover students fill available slots or create new benches
    leftover = []
    for d in depts:
        while queues[d]:
            leftover.append((d, queues[d].pop(0)))

    for st in leftover:
        placed = False
        for b in benches:
            if b[0] is None:
                b[0] = st
                placed = True
                break
            elif b[1] is None:
                b[1] = st
                placed = True
                break
        if not placed and len(benches) < max_benches:
            benches.append([st, None])

    return benches


def assign_bench_positions(benches, rows, cols, students_per_bench=2):
    """Maps benches to row and column grid with bench group letters A, B, C..."""
    result = []
    for index, bench in enumerate(benches):
        r = index % rows
        c = index // rows
        bench_no = index + 1
        grp_letter = column_letter(c)

        left = bench[0]
        right = bench[1] if students_per_bench == 2 else None

        def format_student(slot, st):
            if not st:
                return None
            dept, reg = st
            return {
                "Slot": slot,
                "Department": dept,
                "Register Number": reg,
                "Seat": f"{grp_letter}{r + 1}-{slot}",
            }

        result.append({
            "Bench": bench_no,
            "Row": r + 1,
            "Column": c + 1,
            "Group Letter": grp_letter,
            "Student 1": format_student("A", left),
            "Student 2": format_student("B", right),
        })
    return result


def normalize_bench(bench):
    if isinstance(bench, dict):
        return bench
    return {"Bench": 0, "Row": 0, "Column": 0, "Group Letter": "A", "Student 1": None, "Student 2": None}


# ---------------------------------------------------------------------------
# PDF Generation (Landscape A4 matching college reference style)
# ---------------------------------------------------------------------------

def create_pdf(halls, settings):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=0.8 * cm,
        rightMargin=0.8 * cm,
        topMargin=0.8 * cm,
        bottomMargin=0.8 * cm,
        title=f"{settings.get('college_name', 'College')} - Seating Order",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("ColTitle", fontName="Helvetica-Bold", fontSize=13, alignment=TA_CENTER, leading=16)
    sub_style = ParagraphStyle("ColSub", fontName="Helvetica-Bold", fontSize=10, alignment=TA_CENTER, leading=13)
    order_style = ParagraphStyle("Order", fontName="Helvetica-Bold", fontSize=12, alignment=TA_CENTER, leading=15, spaceAfter=4)
    meta_style = ParagraphStyle("Meta", fontName="Helvetica-Bold", fontSize=8.5, alignment=TA_CENTER)

    elements = []
    is_single = int(settings.get("students_per_bench", 2)) == 1

    for h_idx, hall in enumerate(halls):
        elements.append(Paragraph(settings.get("college_name", "COLLEGE").upper(), title_style))
        elements.append(Paragraph(settings.get("exam_title", "Examination"), sub_style))
        if settings.get("exam_period"):
            elements.append(Paragraph(settings.get("exam_period", ""), sub_style))
        elements.append(Paragraph("SEATING ORDER", order_style))

        # Meta box
        meta_table = Table(
            [[
                Paragraph(f"<b>Session :</b> {settings.get('session', 'FN')}", meta_style),
                Paragraph(f"<b>Hall No :</b> {hall.get('label', 'Hall')}", meta_style),
                Paragraph(f"<b>Exam Date :</b> {settings.get('exam_date', '')}", meta_style),
            ]],
            colWidths=[8.8 * cm, 8.8 * cm, 8.8 * cm],
        )
        meta_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.75, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 0.3 * cm))

        # Main Seating Order Table
        benches = hall.get("benches", [])
        cols = hall.get("cols", 5)
        rows_count = hall.get("rows", 5)

        # Build side-by-side bench groups (A, B, C, D, E...)
        header_grp = []
        header_sub = []
        for c in range(cols):
            grp_name = column_letter(c)
            # Find department names for this column group
            grp_benches = [b for b in benches if b.get("Column") == (c + 1)]
            d1_names = list({b["Student 1"]["Department"] for b in grp_benches if b.get("Student 1")})
            d2_names = list({b["Student 2"]["Department"] for b in grp_benches if b.get("Student 2")})

            d1_label = " / ".join(d1_names) if d1_names else "Vacant"
            d2_label = " / ".join(d2_names) if d2_names else "Vacant"

            if is_single:
                header_grp.extend([grp_name, ""])
                header_sub.extend(["", d1_label])
            else:
                header_grp.extend([grp_name, "", ""])
                header_sub.extend(["", d1_label, d2_label])

        grid_rows = [header_grp, header_sub]

        for r in range(rows_count):
            row_data = []
            for c in range(cols):
                target_bench_no = c * rows_count + (r + 1)
                match_b = next((b for b in benches if b.get("Bench") == target_bench_no), None)
                if match_b:
                    s1 = match_b.get("Student 1")
                    s2 = match_b.get("Student 2")
                    if is_single:
                        row_data.extend([
                            str(match_b.get("Bench", "")),
                            s1.get("Register Number", "") if s1 else "",
                        ])
                    else:
                        row_data.extend([
                            str(match_b.get("Bench", "")),
                            s1.get("Register Number", "") if s1 else "",
                            s2.get("Register Number", "") if s2 else "",
                        ])
                else:
                    row_data.extend(["", ""] if is_single else ["", "", ""])
            grid_rows.append(row_data)

        # Calculate column widths
        total_width = 26.5 * cm
        num_cols = len(header_grp)
        col_w = total_width / num_cols

        tstyle = [
            ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.black),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold"),
            ("FONTNAME", (0, 2), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]

        # Add spans for group letters across their sub-columns
        step = 2 if is_single else 3
        for i in range(0, num_cols, step):
            tstyle.append(("SPAN", (i, 0), (i + step - 1, 0)))
            tstyle.append(("BACKGROUND", (i, 0), (i + step - 1, 0), colors.HexColor("#f1f5f9")))
            tstyle.append(("BACKGROUND", (i, 1), (i + step - 1, 1), colors.HexColor("#f8fafc")))

        main_table = Table(grid_rows, colWidths=[col_w] * num_cols)
        main_table.setStyle(TableStyle(tstyle))
        elements.append(main_table)
        elements.append(Spacer(1, 0.4 * cm))

        # Department count summary
        dept_counts = {}
        for b in benches:
            for k in ("Student 1", "Student 2"):
                st = b.get(k)
                if st and st.get("Department"):
                    d = st["Department"]
                    dept_counts[d] = dept_counts.get(d, 0) + 1

        summary_data = [["Department", "Count"]]
        for d, cnt in dept_counts.items():
            summary_data.append([d, str(cnt).zfill(2)])
        summary_data.append(["TOTAL", str(sum(dept_counts.values())).zfill(2)])

        sm_table = Table(summary_data, colWidths=[4.5 * cm, 2.0 * cm], hAlign="LEFT")
        sm_table.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
            ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        elements.append(sm_table)
        elements.append(Spacer(1, 0.6 * cm))

        # Signatures
        sig_table = Table(
            [[Paragraph("<b>Controller of Examinations</b>", meta_style), Paragraph("<b>Principal</b>", meta_style)]],
            colWidths=[12.0 * cm, 12.0 * cm],
        )
        elements.append(sig_table)

        if h_idx < len(halls) - 1:
            elements.append(PageBreak())

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


# ---------------------------------------------------------------------------
# Excel Generation
# ---------------------------------------------------------------------------

def create_excel(halls, settings):
    buffer = io.BytesIO()
    is_single = int(settings.get("students_per_bench", 2)) == 1

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary_rows = []
        overall_counts = {}

        for hall in halls:
            benches = hall.get("benches", [])
            sheet_rows = []

            for b in benches:
                s1 = b.get("Student 1")
                s2 = b.get("Student 2")

                if is_single:
                    sheet_rows.append({
                        "Bench No": b.get("Bench"),
                        "Group": b.get("Group Letter"),
                        "Row": b.get("Row"),
                        "Column": b.get("Column"),
                        "Department": s1.get("Department", "") if s1 else "",
                        "Register Number": s1.get("Register Number", "") if s1 else "",
                    })
                else:
                    sheet_rows.append({
                        "Bench No": b.get("Bench"),
                        "Group": b.get("Group Letter"),
                        "Row": b.get("Row"),
                        "Column": b.get("Column"),
                        "Student 1 Department": s1.get("Department", "") if s1 else "",
                        "Student 1 Register No": s1.get("Register Number", "") if s1 else "",
                        "Student 2 Department": s2.get("Department", "") if s2 else "",
                        "Student 2 Register No": s2.get("Register Number", "") if s2 else "",
                    })

                for s in (s1, s2):
                    if s and s.get("Department"):
                        d = s["Department"]
                        overall_counts[d] = overall_counts.get(d, 0) + 1

            sheet_name = re.sub(r"[\[\]:*?/\\]", "_", hall.get("label", "Hall"))[:31]
            pd.DataFrame(sheet_rows).to_excel(writer, sheet_name=sheet_name, index=False)

        # Department Summary Sheet
        summary_records = [{"Department": d, "Student Count": c} for d, c in overall_counts.items()]
        summary_records.append({"Department": "TOTAL", "Student Count": sum(overall_counts.values())})
        pd.DataFrame(summary_records).to_excel(writer, sheet_name="Department Summary", index=False)

    buffer.seek(0)
    return buffer.read()


# ---------------------------------------------------------------------------
# HTML Web Interface
# ---------------------------------------------------------------------------

HTML_TEMPLATE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Smart Exam Hall Seating Arrangement System</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body { background: #f8fafc; color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
.hero { background: #0f172a; color: #fff; padding: 2.5rem 0; border-bottom: 3px solid #3b82f6; }
.cardx { background: #fff; border: 1px solid #e2e8f0; border-radius: 14px; box-shadow: 0 4px 20px rgba(0,0,0,0.03); }
.sec-title { font-weight: 700; font-size: 1.1rem; }
.badge-bench { cursor: pointer; padding: 8px 18px; border-radius: 8px; font-weight: 600; border: 1px solid #cbd5e1; }
.badge-bench.active { background: #2563eb; color: #fff; border-color: #2563eb; }
.dept-row { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px; margin-bottom: 10px; }
.sheet-preview { background: #fff; border: 2px solid #000; padding: 24px; min-width: 800px; font-family: Arial, sans-serif; }
.sheet-table { border: 1px solid #000; width: 100%; text-align: center; border-collapse: collapse; font-size: 11px; }
.sheet-table th, .sheet-table td { border: 1px solid #000; padding: 4px 6px; }
@media print {
  body { background: #fff; }
  .no-print { display: none !important; }
  .sheet-preview { border: none !important; padding: 0 !important; min-width: 100% !important; }
}
</style>
</head>
<body>
<div class="hero no-print mb-4">
  <div class="container">
    <h2 class="fw-bold mb-1">Smart Exam Hall Seating Arrangement System</h2>
    <div class="text-secondary small">Deterministic College Seating Order Generator · Reference-image layout</div>
  </div>
</div>

<div class="container pb-5">
  <div id="alertBox" class="no-print"></div>

  <form id="seatingForm" class="cardx p-4 mb-4 no-print">
    <!-- Section 1 -->
    <h5 class="sec-title mb-3">1. Examination Details</h5>
    <div class="row g-3">
      <div class="col-md-6">
        <label class="form-label small fw-semibold">College / Institution Name</label>
        <input class="form-control" name="college_name" value="INDRA GANESAN COLLEGE OF ENGINEERING">
      </div>
      <div class="col-md-6">
        <label class="form-label small fw-semibold">Examination Title</label>
        <input class="form-control" name="exam_title" value="Continuous Internal Assessment - I">
      </div>
      <div class="col-md-6">
        <label class="form-label small fw-semibold">Exam Period</label>
        <input class="form-control" name="exam_period" value="EXAMINATIONS - NOV/DEC - 2026">
      </div>
      <div class="col-md-3">
        <label class="form-label small fw-semibold">Session</label>
        <select class="form-select" name="session">
          <option value="FN" selected>FN (Forenoon)</option>
          <option value="AN">AN (Afternoon)</option>
        </select>
      </div>
      <div class="col-md-3">
        <label class="form-label small fw-semibold">Exam Date</label>
        <input type="date" class="form-control" name="exam_date" value="2026-11-20">
      </div>
    </div>

    <hr class="my-4">

    <!-- Section 2: Students Per Bench -->
    <h5 class="sec-title mb-2">2. Key Feature: Students Per Bench</h5>
    <p class="text-muted small">Select whether each bench holds 1 student or 2 students. Never allows 3.</p>
    
    <div class="d-flex gap-2 mb-3">
      <div id="benchOpt1" class="badge-bench" onclick="setBenchCount(1)">1 Student per Bench</div>
      <div id="benchOpt2" class="badge-bench active" onclick="setBenchCount(2)">2 Students per Bench</div>
    </div>
    <input type="hidden" name="students_per_bench" id="students_per_bench" value="2">

    <!-- Hall config -->
    <div class="row g-3 mt-1">
      <div class="col-md-3">
        <label class="form-label small fw-semibold">Hall Name / Prefix</label>
        <input class="form-control" name="hall_name" value="LB-6">
      </div>
      <div class="col-md-3">
        <label class="form-label small fw-semibold">Students Per Hall</label>
        <input type="number" class="form-control" name="students_per_hall" id="students_per_hall" value="50">
      </div>
      <div class="col-md-3">
        <label class="form-label small fw-semibold">Number of Rows</label>
        <input type="number" class="form-control" name="rows" id="rows" value="5" min="1">
      </div>
      <div class="col-md-3">
        <label class="form-label small fw-semibold">Benches per Row (Columns)</label>
        <input type="number" class="form-control" name="cols" id="cols" value="5" min="1">
      </div>
    </div>

    <div class="alert alert-primary mt-3 py-2 small">
      Hall Capacity: <strong id="capVal">50</strong> students (<span id="benchVal">25</span> benches × <span id="mulVal">2</span> students).
    </div>

    <hr class="my-4">

    <!-- Section 3: Departments -->
    <div class="d-flex justify-content-between align-items-center mb-2">
      <div>
        <h5 class="sec-title mb-0">3. Department & Register Number Ranges</h5>
        <div class="text-muted small">Provide start and end numbers. System generates sequential registers.</div>
      </div>
      <div class="d-flex gap-2">
        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="loadSampleTest()">Load Test Case (50 Students)</button>
        <button type="button" class="btn btn-sm btn-primary" onclick="addDeptRow()">+ Add Department</button>
      </div>
    </div>

    <div id="deptContainer" class="mt-3"></div>

    <button type="submit" class="btn btn-primary btn-lg w-100 mt-4 fw-bold">Generate Seating Order</button>
  </form>

  <!-- Results View -->
  <div id="resultsWrapper" class="d-none">
    <div class="cardx p-3 mb-4 no-print d-flex justify-content-between align-items-center flex-wrap gap-2">
      <div>
        <h6 class="fw-bold mb-0">Seating Plan Generated Successfully</h6>
        <div class="small text-muted" id="statsText"></div>
      </div>
      <div class="d-flex gap-2">
        <button class="btn btn-sm btn-primary" onclick="downloadFile('pdf')">Download PDF</button>
        <button class="btn btn-sm btn-success" onclick="downloadFile('excel')">Download Excel</button>
        <button class="btn btn-sm btn-dark" onclick="window.print()">Print</button>
      </div>
    </div>

    <div id="sheetContainer" class="overflow-auto mb-4"></div>
  </div>
</div>

<script>
let curHalls = [];
let curSettings = {};

function setBenchCount(val) {
  document.getElementById("students_per_bench").value = val;
  document.getElementById("benchOpt1").classList.toggle("active", val === 1);
  document.getElementById("benchOpt2").classList.toggle("active", val === 2);
  updateCap();
}

function updateCap() {
  const r = +document.getElementById("rows").value || 1;
  const c = +document.getElementById("cols").value || 1;
  const b = +document.getElementById("students_per_bench").value || 2;
  const totalBenches = r * c;
  document.getElementById("benchVal").textContent = totalBenches;
  document.getElementById("mulVal").textContent = b;
  document.getElementById("capVal").textContent = totalBenches * b;
}

document.getElementById("rows").oninput = updateCap;
document.getElementById("cols").oninput = updateCap;
updateCap();

function addDeptRow(name="", start="", end="") {
  const div = document.createElement("div");
  div.className = "dept-row row g-2 align-items-end";
  div.innerHTML = `
    <div class="col-md-4">
      <label class="form-label small fw-semibold">Department Name</label>
      <input class="form-control form-control-sm d-name" value="${name}" placeholder="e.g. II IT">
    </div>
    <div class="col-md-3">
      <label class="form-label small fw-semibold">Start Register No.</label>
      <input class="form-control form-control-sm d-start" value="${start}" placeholder="811225205045">
    </div>
    <div class="col-md-3">
      <label class="form-label small fw-semibold">End Register No.</label>
      <input class="form-control form-control-sm d-end" value="${end}" placeholder="811225205069">
    </div>
    <div class="col-md-2">
      <button type="button" class="btn btn-sm btn-outline-danger w-100" onclick="this.closest('.dept-row').remove()">Remove</button>
    </div>
  `;
  document.getElementById("deptContainer").appendChild(div);
}

function loadSampleTest() {
  document.getElementById("deptContainer").innerHTML = "";
  addDeptRow("II IT", "811225205045", "811225205069");
  addDeptRow("III BME", "811224121026", "811224121047");
  addDeptRow("II MBA", "811225631022", "811225631024");
}
loadSampleTest();

document.getElementById("seatingForm").onsubmit = async (e) => {
  e.preventDefault();
  const alertBox = document.getElementById("alertBox");
  alertBox.innerHTML = "";

  const fd = new FormData(e.target);
  const rows = document.querySelectorAll(".dept-row");
  rows.forEach(r => {
    fd.append("dept_name[]", r.querySelector(".d-name").value.trim());
    fd.append("start_reg[]", r.querySelector(".d-start").value.trim());
    fd.append("end_reg[]", r.querySelector(".d-end").value.trim());
  });

  try {
    const res = await fetch("/generate", { method: "POST", body: fd });
    const data = await res.json();
    if (!data.success) throw new Error(data.error);

    curHalls = data.halls;
    curSettings = data.settings;

    document.getElementById("statsText").textContent = 
      `Total Students: ${data.stats.total_students} | Total Benches: ${data.stats.total_benches} | Capacity: ${data.stats.capacity}`;
    document.getElementById("resultsWrapper").classList.remove("d-none");
    renderSheet();
    window.scrollTo({ top: document.getElementById("resultsWrapper").offsetTop - 20, behavior: "smooth" });
  } catch (err) {
    alertBox.innerHTML = `<div class="alert alert-danger py-2">${err.message}</div>`;
  }
};

function renderSheet() {
  const container = document.getElementById("sheetContainer");
  container.innerHTML = "";
  const isSingle = (+curSettings.students_per_bench === 1);

  curHalls.forEach(hall => {
    const sheet = document.createElement("div");
    sheet.className = "sheet-preview mb-4";

    let html = `
      <div class="text-center mb-3">
        <h5 class="fw-bold mb-0 text-uppercase">${curSettings.college_name}</h5>
        <div class="fw-bold small">${curSettings.exam_title}</div>
        <div class="small">${curSettings.exam_period || ""}</div>
        <div class="fw-bold mt-1 text-decoration-underline">SEATING ORDER</div>
      </div>

      <div class="row text-center small fw-bold border border-dark py-1 mx-0 mb-3 bg-light">
        <div class="col-4 border-end border-dark">Session : ${curSettings.session}</div>
        <div class="col-4 border-end border-dark">Hall No : ${hall.label}</div>
        <div class="col-4">Exam Date : ${curSettings.exam_date}</div>
      </div>
    `;

    // Group columns side-by-side
    html += `<table class="sheet-table mb-4"><thead><tr>`;
    for (let c = 0; c < hall.cols; c++) {
      const letter = String.fromCharCode(65 + c);
      html += `<th colspan="${isSingle ? 2 : 3}">${letter}</th>`;
    }
    html += `</tr><tr>`;

    for (let c = 0; c < hall.cols; c++) {
      const grpBenches = hall.benches.filter(b => b.Column === (c + 1));
      const d1 = [...new Set(grpBenches.map(b => b["Student 1"] ? b["Student 1"].Department : ""))].filter(Boolean).join(" / ");
      const d2 = [...new Set(grpBenches.map(b => b["Student 2"] ? b["Student 2"].Department : ""))].filter(Boolean).join(" / ");

      html += `<th style="width:30px;"></th><th>${d1 || "Vacant"}</th>`;
      if (!isSingle) html += `<th>${d2 || "Vacant"}</th>`;
    }
    html += `</tr></thead><tbody>`;

    for (let r = 0; r < hall.rows; r++) {
      html += `<tr>`;
      for (let c = 0; c < hall.cols; c++) {
        const benchNo = c * hall.rows + (r + 1);
        const b = hall.benches.find(x => x.Bench === benchNo);
        if (b) {
          const s1 = b["Student 1"] ? b["Student 1"]["Register Number"] : "";
          const s2 = b["Student 2"] ? b["Student 2"]["Register Number"] : "";
          html += `<td class="fw-bold">${b.Bench}</td><td>${s1}</td>`;
          if (!isSingle) html += `<td>${s2}</td>`;
        } else {
          html += `<td></td><td></td>${!isSingle ? '<td></td>' : ''}`;
        }
      }
      html += `</tr>`;
    }
    html += `</tbody></table>`;

    // Department summary & signature
    let deptCounts = {};
    hall.benches.forEach(b => {
      ['Student 1', 'Student 2'].forEach(k => {
        if (b[k] && b[k].Department) {
          deptCounts[b[k].Department] = (deptCounts[b[k].Department] || 0) + 1;
        }
      });
    });

    html += `
      <div class="d-flex justify-content-between align-items-start mt-3">
        <div style="width: 220px;">
          <table class="sheet-table">
            <thead class="bg-light"><tr><th>Department</th><th>Count</th></tr></thead>
            <tbody>
              ${Object.entries(deptCounts).map(([d, cnt]) => `<tr><td class="text-start ps-2">${d}</td><td class="fw-bold">${String(cnt).padStart(2, '0')}</td></tr>`).join("")}
              <tr class="fw-bold bg-light"><td class="text-start ps-2">TOTAL</td><td>${String(hall.student_count).padStart(2, '0')}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="d-flex justify-content-between text-center mt-5" style="width: 450px;">
          <div><div style="border-bottom: 1px solid #000; width: 160px; margin-bottom: 4px;"></div><small class="fw-bold">Controller of Examinations</small></div>
          <div><div style="border-bottom: 1px solid #000; width: 160px; margin-bottom: 4px;"></div><small class="fw-bold">Principal</small></div>
        </div>
      </div>
    `;

    sheet.innerHTML = html;
    container.appendChild(sheet);
  });
}

async function downloadFile(type) {
  const url = type === 'pdf' ? '/download/pdf' : '/download/excel';
  const fname = type === 'pdf' ? 'Seating_Order.pdf' : 'Seating_Order.xlsx';
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ halls: curHalls, settings: curSettings })
  });
  if (!res.ok) { alert(await res.text()); return; }
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = fname;
  a.click();
}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Flask Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/generate", methods=["POST"])
def generate():
    try:
        f = request.form
        college_name = f.get("college_name", "").strip() or "INDRA GANESAN COLLEGE OF ENGINEERING"
        exam_title = f.get("exam_title", "").strip() or "Continuous Internal Assessment - I"
        exam_period = f.get("exam_period", "").strip() or "EXAMINATIONS - NOV/DEC - 2026"
        session = f.get("session", "FN").strip().upper()
        exam_date = f.get("exam_date", datetime.now().strftime("%Y-%m-%d")).strip()
        hall_name = f.get("hall_name", "LB-6").strip()

        students_per_bench = int(f.get("students_per_bench", 2))
        if students_per_bench not in (1, 2):
            raise ValueError("Students per bench must be either 1 or 2.")

        rows = max(1, int(f.get("rows", 5)))
        cols = max(1, int(f.get("cols", 5)))
        single_hall_cap = rows * cols * students_per_bench

        students_per_hall = int(f.get("students_per_hall", single_hall_cap))
        max_hall_capacity = min(students_per_hall, single_hall_cap)

        # Department parsing
        dept_names = f.getlist("dept_name[]")
        start_regs = f.getlist("start_reg[]")
        end_regs = f.getlist("end_reg[]")

        raw_depts = []
        for n, s, e in zip(dept_names, start_regs, end_regs):
            if n.strip() or s.strip() or e.strip():
                raw_depts.append({"Department": n.strip(), "Start": s.strip(), "End": e.strip()})

        dept_students = build_department_students(raw_depts)
        if not dept_students:
            raise ValueError("Please provide at least one valid department with start and end register numbers.")

        total_students = sum(len(v) for v in dept_students.values())
        halls_needed = (total_students + max_hall_capacity - 1) // max_hall_capacity

        master_queues = {d: list(regs) for d, regs in dept_students.items()}
        depts = list(master_queues.keys())
        halls = []

        for h in range(halls_needed):
            hall_slots = max_hall_capacity
            hall_dept_students = {d: [] for d in depts}

            # Prioritize first 2 departments
            while hall_slots > 0 and any(master_queues[d] for d in depts[:2]):
                for d in depts[:2]:
                    if hall_slots <= 0:
                        break
                    if master_queues[d]:
                        hall_dept_students[d].append(master_queues[d].pop(0))
                        hall_slots -= 1

            # Fill remainder
            for d in depts[2:]:
                while hall_slots > 0 and master_queues[d]:
                    hall_dept_students[d].append(master_queues[d].pop(0))
                    hall_slots -= 1

            hall_dept_students = {d: v for d, v in hall_dept_students.items() if v}
            hall_count = sum(len(v) for v in hall_dept_students.values())
            if hall_count == 0:
                break

            max_benches = rows * cols
            raw_benches = make_benches(hall_dept_students, max_benches, students_per_bench)
            positioned = assign_bench_positions(raw_benches, rows, cols, students_per_bench)

            lbl = hall_name if halls_needed == 1 else f"{hall_name}-{h + 1}"
            halls.append({
                "label": lbl,
                "benches": positioned,
                "rows": rows,
                "cols": cols,
                "student_count": hall_count,
            })

        return jsonify({
            "success": True,
            "halls": halls,
            "settings": {
                "college_name": college_name,
                "exam_title": exam_title,
                "exam_period": exam_period,
                "session": session,
                "exam_date": exam_date,
                "students_per_bench": students_per_bench,
            },
            "stats": {
                "total_students": total_students,
                "total_benches": sum(len(h["benches"]) for h in halls),
                "capacity": single_hall_cap,
            }
        })
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": f"Error: {str(e)}"}), 500


@app.route("/download/pdf", methods=["POST"])
def download_pdf():
    try:
        data = request.get_json(force=True)
        pdf = create_pdf(data.get("halls", []), data.get("settings", {}))
        return send_file(io.BytesIO(pdf), mimetype="application/pdf", as_attachment=True, download_name="Seating_Order.pdf")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/download/excel", methods=["POST"])
def download_excel():
    try:
        data = request.get_json(force=True)
        xl = create_excel(data.get("halls", []), data.get("settings", {}))
        return send_file(io.BytesIO(xl), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name="Seating_Order.xlsx")
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
