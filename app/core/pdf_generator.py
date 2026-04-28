import io
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from typing import List, Dict

def generate_invoice_pdf(client_name: str, company: str, items: List[Dict[str, str]], total_amount: float) -> bytes:
    """
    Generate an invoice PDF in-memory using reportlab.
    
    Args:
        client_name: Full name of the client.
        company: Company name, if any.
        items: List of dictionaries with 'description' and 'amount' keys.
        total_amount: Total sum of the invoice.

    Returns:
        The generated PDF as a bytes object.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=18)
    
    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    normal_style = styles["Normal"]
    
    elements = []
    
    # Header: TitanCode Technologies
    elements.append(Paragraph("<b>TitanCode Technologies</b>", title_style))
    elements.append(Paragraph("Premium Development Agency", normal_style))
    elements.append(Spacer(1, 20))
    
    # Invoice To
    elements.append(Paragraph(f"<b>Invoice To:</b>", styles["Heading3"]))
    elements.append(Paragraph(client_name, normal_style))
    if company and company != "N/A":
        elements.append(Paragraph(company, normal_style))
    elements.append(Spacer(1, 20))
    
    # Table data
    data = [["Description", "Amount ($)"]]
    
    for item in items:
        data.append([item["description"], f"${float(item['amount']):.2f}"])
        
    data.append(["<b>Total</b>", f"<b>${total_amount:.2f}</b>"])
    
    # Table styling
    t = Table(data, colWidths=[350, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#f3f4f6")),
        ('GRID', (0, 0), (-1, -1), 1, colors.HexColor("#e5e7eb")),
    ]))
    
    elements.append(t)
    elements.append(Spacer(1, 40))
    
    # Footer Note
    elements.append(Paragraph("Thank you for choosing TitanCode Technologies. You can pay securely online via our active invoice link.", normal_style))
    
    # Build PDF
    doc.build(elements)
    
    pdf_bytes = buffer.getvalue()
    buffer.close()
    
    return pdf_bytes
