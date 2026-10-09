"""Certificate rendering for the single built-in PDF design."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas


def render_certificate(recipient: dict, destination: Path) -> None:
    """Render one certificate PDF. Raises on filesystem or PDF errors."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    page = landscape(letter)
    pdf = canvas.Canvas(str(destination), pagesize=page)
    width, height = page
    pdf.setStrokeColor(colors.HexColor("#244b68"))
    pdf.setLineWidth(4)
    pdf.roundRect(30, 30, width - 60, height - 60, 16, stroke=1, fill=0)
    pdf.setFillColor(colors.HexColor("#244b68"))
    pdf.setFont("Helvetica-Bold", 30)
    pdf.drawCentredString(width / 2, height - 150, "CERTIFICATE OF COMPLETION")
    pdf.setFillColor(colors.HexColor("#333333"))
    pdf.setFont("Helvetica", 16)
    pdf.drawCentredString(width / 2, height - 205, "This certificate is proudly presented to")
    pdf.setFillColor(colors.HexColor("#152f45"))
    pdf.setFont("Helvetica-Bold", 27)
    pdf.drawCentredString(width / 2, height - 260, recipient["full_name"])
    pdf.setFillColor(colors.HexColor("#333333"))
    pdf.setFont("Helvetica", 16)
    pdf.drawCentredString(width / 2, height - 305, f"for completing {recipient['course_name']}")
    pdf.setFont("Helvetica", 12)
    pdf.drawCentredString(width / 2, 95, f"Issued {recipient['issue_date']}")
    pdf.save()
