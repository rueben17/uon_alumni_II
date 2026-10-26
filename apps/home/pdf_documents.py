# apps/home/pdf_documents.py
"""
PDF document builders for payment confirmation -- the acknowledgement
letter and invoice emailed to a member once their payment is confirmed
(Payment.mark_as_completed in apps/home/models.py -> the
send_payment_confirmation_documents task in apps/home/tasks.py). Follows
the same reportlab platypus pattern already used for the QR membership
card (apps/home/views.py's download_alumni_qr_code) -- SimpleDocTemplate
+ flowables, not raw canvas drawing.

A clean equivalent of the Association's old letter/invoice layout
(docs/Acknowledgement_*.pdf, docs/Invoice_*.pdf), not a pixel replica:
no vendor-specific barcode/"digital signature" hash and no diagonal PAID
ribbon graphic (2026-10-27 decision) -- the invoice's QR code replaces
the barcode instead, carrying a plain informational payload rather than
a verification link (no public payment-verification endpoint exists to
point it at).

Signature/stamp images don't exist in this repo yet -- both are read
from fixed static paths and silently omitted if the file isn't there,
so dropping in the real PNGs later needs no code change.
"""
import io
from pathlib import Path

import qrcode
from django.conf import settings
from django.utils import timezone

from apps.home.models import Membership
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ASSOCIATION_NAME = "UNIVERSITY OF NAIROBI ALUMNI ASSOCIATION"
ASSOCIATION_ADDRESS_LINES = [
    "P.O. Box 30490-00100, Nairobi, Kenya",
    "Kolobot Drive, Off Arboretum Drive, Off State House Rd",
]
ASSOCIATION_CONTACT = (
    "Email: alumni@uonbi.ac.ke  |  Website: uonalumni.org  |  "
    "Tel: +254 020 4916713, 0724 820 908"
)

_IMAGES_DIR = Path(settings.BASE_DIR) / "static" / "images"
_CREST_PATH = _IMAGES_DIR / "UoN CREST_new-01.png"
_SIGNATURE_PATH = _IMAGES_DIR / "signatures" / "executive_director.png"
_STAMP_PATH = _IMAGES_DIR / "stamps" / "uonaa_seal.png"


def _local(dt):
    return timezone.localtime(dt) if dt else None


def _resolve_membership(payment):
    """payment.membership is only reliably set for installment-linked
    payments (see that field's own comment, apps/home/models.py) -- a
    lump-sum payment's services.confirm_payment() activates a Membership
    without ever writing it back onto the Payment row. Falls back to the
    same lookup the rest of the app uses for "what does this member
    currently hold" (e.g. AlumniProfileDetailView, download_alumni_qr_code)."""
    return payment.membership or Membership.objects.current_active_for(payment.alumni.user)


def _validity_label(membership):
    if membership.is_lifetime:
        return "Lifetime Membership"
    if membership.started_on and membership.expires_on:
        return f"{membership.started_on:%B %Y} - {membership.expires_on:%B %Y}"
    return "—"


def _base_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "AssociationName", parent=styles["Title"], fontSize=14, alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "Small", parent=styles["Normal"], fontSize=8, alignment=TA_CENTER,
        textColor=colors.HexColor("#444444"),
    ))
    return styles


def _letterhead(elements, styles):
    if _CREST_PATH.exists():
        crest = RLImage(str(_CREST_PATH), width=0.9 * inch, height=0.9 * inch)
        crest.hAlign = "CENTER"
        elements.append(crest)
        elements.append(Spacer(1, 0.08 * inch))
    elements.append(Paragraph(ASSOCIATION_NAME, style=styles["AssociationName"]))
    elements.append(Paragraph(ASSOCIATION_CONTACT, style=styles["Small"]))
    for line in ASSOCIATION_ADDRESS_LINES:
        elements.append(Paragraph(line, style=styles["Small"]))
    elements.append(Spacer(1, 0.2 * inch))


def build_acknowledgement_letter_pdf(payment):
    """Builds the membership acknowledgement letter for a confirmed
    Payment as PDF bytes. Callers (apps.home.tasks.
    send_payment_confirmation_documents) only build this once
    Payment.mark_as_completed has activated a membership for this
    member."""
    membership = _resolve_membership(payment)
    user = payment.alumni.user
    profile = user.profile

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, title="UONAA Membership Acknowledgement",
        author="UoN Alumni Association", topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    styles = _base_styles()
    elements = []

    _letterhead(elements, styles)

    today = _local(payment.completion_date or payment.payment_date).date()
    elements.append(Paragraph(f"{today:%d %B, %Y}", style=styles["Normal"]))
    elements.append(Spacer(1, 0.15 * inch))

    elements.append(Paragraph(profile.display_name, style=styles["Normal"]))
    if user.email:
        elements.append(Paragraph(f"Email: {user.email}", style=styles["Normal"]))
    if user.phone:
        elements.append(Paragraph(f"Tel: {user.phone}", style=styles["Normal"]))
    elements.append(Spacer(1, 0.15 * inch))

    first_name = profile.given_name or profile.display_name.split()[0]
    elements.append(Paragraph(f"Dear {first_name},", style=styles["Normal"]))
    elements.append(Spacer(1, 0.1 * inch))
    elements.append(Paragraph(
        "<b>MEMBERSHIP - UNIVERSITY OF NAIROBI ALUMNI ASSOCIATION</b>", style=styles["Normal"],
    ))
    elements.append(Spacer(1, 0.05 * inch))
    elements.append(Paragraph(
        "I acknowledge your membership with the University of Nairobi Alumni "
        "Association. Your membership details are as follows;",
        style=styles["Normal"],
    ))
    elements.append(Spacer(1, 0.15 * inch))

    table = Table(
        [
            ["Category", membership.tier.name],
            ["Membership No.", membership.membership_number or "—"],
            ["Validity", _validity_label(membership)],
        ],
        colWidths=[1.8 * inch, 3.8 * inch],
    )
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 0.2 * inch))

    elements.append(Paragraph(
        "On behalf of the UONAA, I welcome you to service and fellowship of the Association.",
        style=styles["Normal"],
    ))
    elements.append(Spacer(1, 0.3 * inch))

    elements.append(Paragraph("Yours in service,", style=styles["Normal"]))
    elements.append(Paragraph(f"<b>{ASSOCIATION_NAME}</b>", style=styles["Normal"]))
    elements.append(Spacer(1, 0.1 * inch))

    if _SIGNATURE_PATH.exists():
        elements.append(RLImage(str(_SIGNATURE_PATH), width=1.6 * inch, height=0.6 * inch))

    elements.append(Paragraph(f"<b>{settings.UONAA_SIGNATORY_NAME.upper()}</b>", style=styles["Normal"]))
    elements.append(Paragraph(f"<u>{settings.UONAA_SIGNATORY_TITLE.upper()}</u>", style=styles["Normal"]))

    if _STAMP_PATH.exists():
        elements.append(Spacer(1, 0.1 * inch))
        elements.append(RLImage(str(_STAMP_PATH), width=1.2 * inch, height=1.2 * inch))

    doc.build(elements)
    return buffer.getvalue()


def build_invoice_pdf(payment):
    """Builds the invoice for a confirmed Payment as PDF bytes."""
    membership = _resolve_membership(payment)
    tier = payment.membership_tier or (membership.tier if membership else None)
    user = payment.alumni.user
    profile = user.profile

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, title="UONAA Invoice", author="UoN Alumni Association",
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
    )
    styles = _base_styles()
    elements = []

    _letterhead(elements, styles)

    bank_lines = [
        f"Mpesa Paybill No. {settings.UONAA_MPESA_PAYBILL}  |  "
        f"Account No. Category - Your Name",
        f"Bank Account No. {settings.UONAA_BANK_ACCOUNT_NUMBER}  |  "
        f"{settings.UONAA_BANK_NAME}  |  Swift Code {settings.UONAA_BANK_SWIFT_CODE}",
    ]
    for line in bank_lines:
        elements.append(Paragraph(line, style=styles["Small"]))
    elements.append(Spacer(1, 0.15 * inch))

    invoice_number = f"INV-{payment.id:06d}"
    invoice_dt = _local(payment.completion_date or payment.payment_date)
    status_label = "PAID" if payment.is_completed else payment.get_payment_status_display().upper()
    status_color = colors.HexColor("#1a7f37") if payment.is_completed else colors.HexColor("#B45309")

    header_table = Table(
        [
            ["Invoice #", invoice_number, "Status", status_label],
            ["Invoice Date", f"{invoice_dt.date():%d %B, %Y}", "", ""],
        ],
        colWidths=[1.1 * inch, 1.9 * inch, 0.9 * inch, 1.5 * inch],
    )
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (3, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (3, 0), (3, 0), status_color),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.15 * inch))

    elements.append(Paragraph("<b>Invoiced To</b>", style=styles["Normal"]))
    elements.append(Paragraph(profile.display_name, style=styles["Normal"]))
    if user.email:
        elements.append(Paragraph(f"Email: {user.email}", style=styles["Normal"]))
    if user.phone:
        elements.append(Paragraph(f"Tel: {user.phone}", style=styles["Normal"]))
    elements.append(Spacer(1, 0.2 * inch))

    description = tier.name if tier else "Membership"
    if membership:
        description = f"{description} ({_validity_label(membership)})"
    amount_str = f"{payment.amount:,.2f}"

    line_items = Table(
        [
            ["Description", "Amount"],
            [description, amount_str],
            ["Sub Total", amount_str],
            ["Total", amount_str],
        ],
        colWidths=[4.6 * inch, 1.4 * inch],
    )
    line_items.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, 1), 0.5, colors.HexColor("#CCCCCC")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 3), "Helvetica-Bold"),
        ("LINEABOVE", (0, 2), (-1, 2), 0.5, colors.HexColor("#CCCCCC")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(line_items)
    elements.append(Spacer(1, 0.2 * inch))

    reference = payment.mpesa_receipt_number or payment.bank_reference or str(payment.transaction_reference)
    balance = membership.balance_due if membership and membership.is_installment_plan else 0

    payments_table = Table(
        [
            ["Date", "Payment Mode", "Details", "Amount"],
            [f"{invoice_dt:%d/%m/%Y %H:%M:%S}", payment.get_payment_method_display(), reference, amount_str],
            ["", "", "Total", amount_str],
            ["", "", "Balance", f"{balance:,.2f}"],
        ],
        colWidths=[1.6 * inch, 1.5 * inch, 1.5 * inch, 1.4 * inch],
    )
    payments_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, 1), 0.5, colors.HexColor("#CCCCCC")),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("FONTNAME", (2, 2), (3, 3), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(Paragraph("<b>Payments</b>", style=styles["Normal"]))
    elements.append(Spacer(1, 0.05 * inch))
    elements.append(payments_table)
    elements.append(Spacer(1, 0.25 * inch))

    qr_payload = f"UONAA {invoice_number} | {description} | KES {amount_str} | {invoice_dt.date():%Y-%m-%d}"
    qr_buffer = io.BytesIO()
    qrcode.make(qr_payload).save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    elements.append(RLImage(qr_buffer, width=1 * inch, height=1 * inch))

    doc.build(elements)
    return buffer.getvalue()
