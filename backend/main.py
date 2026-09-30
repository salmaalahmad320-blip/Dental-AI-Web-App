import io
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .image_processing import annotate_detections, apply_medical_enhancement, decode_image, encode_jpeg
from .openai_report import generate_report
from .yolo_detector import DentalDetector

load_dotenv(Path(__file__).resolve().parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
configured_model_path = Path(os.getenv("MODEL_PATH", "backend/model/best.pt"))
MODEL_PATH = configured_model_path if configured_model_path.is_absolute() else BASE_DIR / configured_model_path
DATA_DIR = BASE_DIR / "backend" / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "cases.db"
ALLOWED_TYPES = {"image/jpeg", "image/png"}

for directory in (UPLOAD_DIR, REPORT_DIR):
    directory.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Dental X-Ray Analyzer", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "*").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
detector = DentalDetector(MODEL_PATH)


def get_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with get_connection() as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS cases (
            case_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            patient_name TEXT NOT NULL DEFAULT '',
            patient_id TEXT NOT NULL DEFAULT '',
            original_filename TEXT NOT NULL,
            image_path TEXT NOT NULL,
            annotated_path TEXT NOT NULL,
            detections_json TEXT NOT NULL,
            report TEXT NOT NULL,
            pdf_path TEXT NOT NULL
        )""")
        columns = {row[1] for row in connection.execute("PRAGMA table_info(cases)")}
        if "patient_name" not in columns:
            connection.execute("ALTER TABLE cases ADD COLUMN patient_name TEXT NOT NULL DEFAULT ''")
        if "patient_id" not in columns:
            connection.execute("ALTER TABLE cases ADD COLUMN patient_id TEXT NOT NULL DEFAULT ''")


def create_pdf(case_id: str, original_path: Path, detections: list[dict], report: str, patient_name: str = "", patient_id: str = "") -> Path:
    from html import escape
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, Table, TableStyle

    pdf_path = REPORT_DIR / f"{case_id}.pdf"
    document = canvas.Canvas(str(pdf_path), pagesize=letter)
    width, height = letter
    margin = 48
    blue = colors.HexColor("#145B87")
    dark_blue = colors.HexColor("#123B5D")
    pale_blue = colors.HexColor("#EAF3F8")
    line_blue = colors.HexColor("#C9DDE8")
    muted = colors.HexColor("#607B8D")
    analysis_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    annotated_path = original_path.with_name(f"{original_path.stem}-annotated.jpg")
    sorted_detections = sorted(detections, key=lambda item: item["confidence"], reverse=True)
    counts = {}
    confidence_bands = {"High": 0, "Medium": 0, "Low": 0}
    for item in sorted_detections:
        counts[item["class"]] = counts.get(item["class"], 0) + 1
        confidence = item["confidence"]
        band = "High" if confidence >= 70 else "Medium" if confidence >= 50 else "Low"
        confidence_bands[band] += 1
    average_confidence = (
        sum(item["confidence"] for item in sorted_detections) / len(sorted_detections)
        if sorted_detections else 0
    )
    review_suggestions = []
    for name in counts:
        review_suggestions.append(
            f"{name}: Review the corresponding radiographic region to confirm the detected finding."
        )
    if any(item["confidence"] < 50 for item in sorted_detections):
        review_suggestions.append(
            "Low-confidence findings: Verify against the original radiograph before drawing clinical conclusions."
        )
        review_suggestions.append(
            "Consider additional clinical or radiographic assessment if deemed appropriate by the treating dental professional."
        )

    body_style = ParagraphStyle(
        "report_body", fontName="Helvetica", fontSize=9.5,
        leading=14, textColor=colors.HexColor("#314F63"), spaceAfter=8,
    )
    report_heading_style = ParagraphStyle(
        "report_heading", parent=body_style, fontName="Helvetica-Bold",
        textColor=dark_blue, spaceBefore=3, spaceAfter=5,
    )
    compact_body_style = ParagraphStyle(
        "compact_report_body", parent=body_style, fontSize=9.5, leading=13,
        spaceAfter=5,
    )
    compact_heading_style = ParagraphStyle(
        "compact_report_heading", parent=compact_body_style,
        fontName="Helvetica-Bold", spaceBefore=3, spaceAfter=4,
    )

    def draw_footer() -> None:
        document.setStrokeColor(line_blue)
        document.line(margin, 42, width - margin, 42)
        document.setFont("Helvetica-Oblique", 8)
        document.setFillColor(muted)
        document.drawString(
            margin, 27,
            "AI-assisted analysis only. Not a final diagnosis. Dentist evaluation is required.",
        )
        document.drawRightString(width - margin, 27, f"Page {document.getPageNumber()}")

    def draw_header() -> None:
        document.setFillColor(dark_blue)
        document.rect(0, height - 92, width, 92, fill=1, stroke=0)
        document.setFillColor(colors.HexColor("#6FD0D0"))
        document.rect(margin, height - 72, 5, 42, fill=1, stroke=0)
        document.setFillColor(colors.white)
        document.setFont("Helvetica-Bold", 20)
        document.drawString(margin + 16, height - 50, "Dental AI Analysis Report")
        document.setFont("Helvetica", 9.5)
        document.drawString(margin + 16, height - 68, "AI-Assisted Dental X-Ray Analysis System")
        document.setFillColor(colors.HexColor("#CDE7F0"))
        document.setFont("Helvetica", 8.5)
        document.drawRightString(width - margin, height - 48, f"CASE {case_id}")
        document.drawRightString(width - margin, height - 64, "AI-ASSISTED RADIOGRAPHIC ANALYSIS")

    def draw_section_title(title: str, y: float) -> float:
        document.setFillColor(blue)
        document.setFont("Helvetica-Bold", 12)
        document.drawString(margin, y, title)
        document.setStrokeColor(line_blue)
        document.line(margin, y - 7, width - margin, y - 7)
        return y - 28

    def draw_image(path: Path, x: float, y: float, max_width: float, max_height: float) -> float:
        image = ImageReader(io.BytesIO(path.read_bytes()))
        image_width, image_height = image.getSize()
        scale = min(max_width / image_width, max_height / image_height)
        draw_width = image_width * scale
        draw_height = image_height * scale
        draw_x = x + (max_width - draw_width) / 2
        draw_y = y + (max_height - draw_height) / 2
        document.setFillColor(colors.HexColor("#F1F6F9"))
        document.setStrokeColor(line_blue)
        document.roundRect(x, y, max_width, max_height, 5, fill=1, stroke=1)
        document.drawImage(image, draw_x, draw_y, width=draw_width, height=draw_height, preserveAspectRatio=True, mask="auto")
        return draw_y

    def draw_report_text(text: str, x: float, y: float, max_width: float, compact: bool = False) -> float:
        text_style = compact_body_style if compact else body_style
        heading_style = compact_heading_style if compact else report_heading_style
        for block in text.split("\n\n"):
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            first_line = lines[0].strip()
            style = heading_style if len(lines) == 1 and not first_line.startswith("-") else text_style
            markup = "<br/>".join(escape(line) for line in lines)
            paragraph = Paragraph(markup, style)
            _, paragraph_height = paragraph.wrap(max_width, height)
            if y - paragraph_height < 58:
                draw_footer()
                draw_header()
                y = height - 120
            paragraph.drawOn(document, x, y - paragraph_height)
            y -= paragraph_height + 3
        return y

    def concise_interpretation(text: str) -> str:
        sections = []
        current_heading = None
        current_lines = []
        headings = {
            "summary": "Summary",
            "confidence interpretation": "Confidence Interpretation",
            "confidence level": "Confidence Interpretation",
        }
        excluded_sections = {
            "detected findings",
            "possible clinical considerations",
            "recommended next steps",
            "disclaimer",
        }
        for line in text.splitlines():
            normalized = re.sub(r"^\s*\d+[.)]\s*", "", line.strip()).rstrip(":").lower()
            if normalized in headings:
                if current_heading and current_lines:
                    sections.append((current_heading, current_lines))
                current_heading = headings[normalized]
                current_lines = []
            elif current_heading and normalized in excluded_sections:
                sections.append((current_heading, current_lines))
                current_heading = None
                current_lines = []
            elif current_heading:
                if re.match(r"^\s*\d+[.)]\s+", line) and current_lines:
                    sections.append((current_heading, current_lines))
                    current_heading = None
                    current_lines = []
                else:
                    current_lines.append(line)
        if current_heading and current_lines:
            sections.append((current_heading, current_lines))
        return "\n\n".join(
            f"{heading}\n" + "\n".join(line for line in lines if line.strip())
            for heading, lines in sections
        )

    document.setTitle(f"Dental AI Analysis Report {case_id}")
    draw_header()
    y = height - 126
    y = draw_section_title("1. Case Summary", y)
    info_table = Table(
        [
            [Paragraph("<b>Case ID</b>", body_style), case_id],
            [Paragraph("<b>Analysis date</b>", body_style), analysis_time],
            [Paragraph("<b>Analysis type</b>", body_style), "AI-Assisted Preliminary Analysis"],
        ],
        colWidths=[1.55 * inch, 4.95 * inch],
    )
    info_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), pale_blue),
        ("TEXTCOLOR", (0, 0), (-1, -1), dark_blue),
        ("FONTNAME", (1, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, line_blue),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    _, table_height = info_table.wrapOn(document, width - 2 * margin, height)
    info_table.drawOn(document, margin, y - table_height)
    y -= table_height + 14

    y = draw_section_title("2. Detection Summary", y)
    summary_rows = [["Metric", "Value"], ["Total detections", str(len(sorted_detections))]]
    summary_rows.extend([
        ["Average confidence", f"{average_confidence:.2f}%" if detections else "N/A"],
        ["High confidence (>= 70%)", str(confidence_bands["High"])],
        ["Medium confidence (50%-69.99%)", str(confidence_bands["Medium"])],
        ["Low confidence (< 50%)", str(confidence_bands["Low"])],
    ])
    class_counts = ", ".join(f"{name}: {count}" for name, count in counts.items())
    summary_rows.append(["Detected class counts", class_counts or "None"])
    summary_table = Table(summary_rows, colWidths=[4.7 * inch, 1.8 * inch])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), blue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 1), (-1, -1), dark_blue),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F9FB")]),
        ("GRID", (0, 0), (-1, -1), 0.5, line_blue),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    _, table_height = summary_table.wrapOn(document, width - 2 * margin, height)
    summary_table.drawOn(document, margin, y - table_height)
    y -= table_height + 14

    y = draw_section_title("3. AI Interpretation", y)
    report = re.sub(r"\bmoderate confidence\b", "medium confidence", report, flags=re.IGNORECASE)
    interpretation_text = concise_interpretation(report)
    if not interpretation_text:
        interpretation_text = (
            "Summary\n"
            "The detailed findings table below contains the complete model output "
            "for this case."
        )
    y = draw_report_text(interpretation_text, margin, y, width - 2 * margin, compact=True)
    y -= 4
    y = draw_section_title("4. AI-Assisted Clinical Review Suggestions", y)
    suggestions_text = "\n".join(f"- {suggestion}" for suggestion in review_suggestions) or "- No detected findings require a class-specific review suggestion."
    draw_report_text(suggestions_text, margin, y, width - 2 * margin, compact=True)

    draw_footer()
    document.showPage()
    draw_header()
    y = draw_section_title("5. Radiographic Images", height - 126)
    image_gap = 12
    image_width = (width - 2 * margin - image_gap) / 2
    image_bottom = 250
    image_height = 340
    draw_image(original_path, margin, image_bottom, image_width, image_height)
    document.setFont("Helvetica-Bold", 9)
    document.setFillColor(muted)
    document.drawCentredString(margin + image_width / 2, image_bottom - 20, "Original Radiograph")
    annotated_x = margin + image_width + image_gap
    if annotated_path.exists():
        draw_image(annotated_path, annotated_x, image_bottom, image_width, image_height)
    else:
        document.setFillColor(colors.HexColor("#F1F6F9"))
        document.setStrokeColor(line_blue)
        document.roundRect(annotated_x, image_bottom, image_width, image_height, 5, fill=1, stroke=1)
        document.setFillColor(muted)
        document.setFont("Helvetica", 9)
        document.drawCentredString(annotated_x + image_width / 2, image_bottom + image_height / 2, "Annotated image unavailable")
    document.setFont("Helvetica-Bold", 9)
    document.setFillColor(muted)
    document.drawCentredString(annotated_x + image_width / 2, image_bottom - 20, "AI Detection Result")

    draw_footer()
    document.showPage()
    draw_header()
    y = draw_section_title("6. Detailed Findings", height - 126)
    detail_rows = [["#", "Finding", "Confidence", "Confidence Level", "Bounding Box"]]
    for index, item in enumerate(sorted_detections, start=1):
        confidence = item["confidence"]
        level = "High" if confidence >= 70 else "Medium" if confidence >= 50 else "Low"
        detail_rows.append([
            f"#{index}", item["class"], f"{confidence:.2f}%", level,
            "[" + ", ".join(f"{value:g}" for value in item["bbox"]) + "]",
        ])
    if not sorted_detections:
        detail_rows.append(["", "No findings detected", "N/A", "N/A", "N/A"])
    detail_table = Table(
        detail_rows,
        colWidths=[0.4 * inch, 1.5 * inch, 1.05 * inch, 1.35 * inch, 2.2 * inch],
        repeatRows=1,
    )
    detail_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), blue),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), dark_blue),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (3, -1), "CENTER"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F9FB")]),
        ("GRID", (0, 0), (-1, -1), 0.5, line_blue),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    table_chunks = detail_table.split(width - 2 * margin, y - 150)
    for index, chunk in enumerate(table_chunks):
        if index:
            draw_footer()
            document.showPage()
            draw_header()
            y = draw_section_title("6. Detailed Findings (continued)", height - 126)
        _, chunk_height = chunk.wrapOn(document, width - 2 * margin, y - 58)
        chunk.drawOn(document, margin, y - chunk_height)
        y -= chunk_height + 12

    if y < 150:
        draw_footer()
        document.showPage()
        draw_header()
        y = draw_section_title("7. Clinical Review", height - 126)
    else:
        y = draw_section_title("7. Clinical Review", y)
    review = Paragraph(
        "The detected findings should be reviewed against the original radiograph by a qualified dental professional. This report does not provide a definitive diagnosis or treatment plan.",
        body_style,
    )
    _, review_height = review.wrap(width - 2 * margin, height)
    review.drawOn(document, margin, y - review_height)
    y -= review_height + 20
    y = draw_section_title("8. Disclaimer", y)
    disclaimer = Paragraph(
        "This report provides an AI-assisted preliminary analysis of the uploaded dental radiograph. It is not a definitive diagnosis and should not replace professional clinical evaluation. All findings should be independently reviewed by a qualified dental professional.",
        body_style,
    )
    _, disclaimer_height = disclaimer.wrap(width - 2 * margin, height)
    disclaimer.drawOn(document, margin, y - disclaimer_height)
    draw_footer()
    document.save()
    return pdf_path


@app.on_event("startup")
def startup() -> None:
    initialize_database()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model_available": MODEL_PATH.exists()}


@app.post("/predict")
async def predict(file: UploadFile = File(...), confidence: float = Form(0.25), patient_name: str = Form(""), patient_id: str = Form("")) -> dict:
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG and PNG images are supported")
    image_bytes = await file.read()
    if not image_bytes or len(image_bytes) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image must be between 1 byte and 15 MB")
    try:
        image_bgr = decode_image(image_bytes)
        enhanced_rgb = apply_medical_enhancement(image_bgr)
        detections, _ = detector.predict(enhanced_rgb, confidence=max(0.0, min(confidence, 1.0)))
    except FileNotFoundError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=f"Unable to analyze image: {error}") from error

    case_id = f"DX-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    patient_name = patient_name.strip()[:120]
    patient_id = patient_id.strip()[:80]
    suffix = ".png" if file.content_type == "image/png" else ".jpg"
    original_path = UPLOAD_DIR / f"{case_id}{suffix}"
    annotated_path = UPLOAD_DIR / f"{case_id}-annotated.jpg"
    original_path.write_bytes(image_bytes)
    annotated_path.write_bytes(encode_jpeg(annotate_detections(enhanced_rgb, detections)))
    report = generate_report(detections)
    pdf_path = create_pdf(case_id, original_path, detections, report, patient_name, patient_id)
    created_at = datetime.now(timezone.utc).isoformat()
    with get_connection() as connection:
        connection.execute(
            "INSERT INTO cases (case_id, created_at, patient_name, patient_id, original_filename, image_path, annotated_path, detections_json, report, pdf_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (case_id, created_at, patient_name, patient_id, file.filename or "x-ray", str(original_path), str(annotated_path), json.dumps(detections), report, str(pdf_path)),
        )
    return {
        "case_id": case_id,
        "created_at": created_at,
        "patient_name": patient_name,
        "patient_id": patient_id,
        "image_url": f"/uploads/{original_path.name}",
        "annotated_image_url": f"/uploads/{annotated_path.name}",
        "detections": detections,
        "report": report,
        "report_url": f"/reports/{case_id}.pdf",
    }


@app.get("/cases")
def cases() -> list[dict]:
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM cases ORDER BY created_at DESC LIMIT 50").fetchall()
    return [
        {
            "case_id": row["case_id"],
            "created_at": row["created_at"],
            "patient_name": row["patient_name"],
            "patient_id": row["patient_id"],
            "original_filename": row["original_filename"],
            "image_url": f"/uploads/{Path(row['image_path']).name}",
            "detections": json.loads(row["detections_json"]),
            "report_url": f"/reports/{row['case_id']}.pdf",
        }
        for row in rows
    ]


@app.get("/reports/{filename}")
def report(filename: str) -> FileResponse:
    safe_name = Path(filename).name
    path = REPORT_DIR / safe_name
    if not path.exists() or path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, media_type="application/pdf", filename=safe_name)


if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
