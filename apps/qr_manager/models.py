import secrets
import uuid
from io import BytesIO

import qrcode
from PIL import Image
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import models
from django.db.models import Q
from django.utils import timezone
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers import CircleModuleDrawer

from apps.staff.models import Department, Employee, ResearchUnit, ServiceUnit


class QRCode(models.Model):
    """
    A scannable credential. The QR image encodes:

        <QR_SCAN_ORIGIN>/qr/<id>/?t=<token>

    - ``id`` (UUID) identifies the badge itself — independent of what
      it points at (employee today; visitor/event labels supported;
      any model later without changing the URL scheme).
    - ``token`` validates it: rotating the token invalidates every
      previously printed copy while the badge keeps its identity.
    """

    class QRType(models.TextChoices):
        ID = "ID", "Main ID Badge"
        TEMP = "TEMP", "Temporary Pass"
        ACCESS = "ACCESS", "Restricted Area Access"
        VISITOR = "VISITOR", "Visitor Pass"
        EVENT = "EVENT", "Event Pass"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Optional link to an employee. Null for visitor/event/etc. codes.
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="employee_qrcode",
        blank=True,
        null=True,
    )

    # Human label for codes with no employee: visitor's name, event
    # name, contractor company — whatever identifies the holder.
    label = models.CharField(max_length=255, blank=True, default="")

    token = models.CharField(max_length=64, unique=True, editable=False)

    qr_type = models.CharField(
        max_length=10, choices=QRType.choices, default=QRType.ID
    )

    issued_at = models.DateTimeField(auto_now_add=True)

    # Null = never expires (permanent ID badges). Set for TEMP,
    # VISITOR, and EVENT passes. Enforcement in verify_scan is
    # deferred by design — the data accrues from day one.
    expires_at = models.DateTimeField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "QR code"
        verbose_name_plural = "QR codes"

    def __str__(self):
        holder = self.employee.full_name if self.employee else (self.label or "unassigned")
        return f"{holder} — {self.get_qr_type_display()}"

    # ---------------- validity ----------------

    @property
    def is_expired(self):
        return self.expires_at is not None and timezone.now() >= self.expires_at

    @property
    def is_valid(self):
        """Single source of truth for badge validity."""
        return self.is_active and not self.is_expired

    @property
    def status(self):
        """Machine-readable status for scan logs (and, later, the
        verify view once validity enforcement is switched on)."""
        if not self.is_active:
            return "REVOKED"
        if self.is_expired:
            return "EXPIRED"
        return "VALID"

    # ---------------- token lifecycle ----------------

    @staticmethod
    def make_token():
        return secrets.token_urlsafe(32)

    def save(self, *args, **kwargs):
        # Every code gets a token from birth; nobody has to remember
        # to call anything before generate_qr().
        if not self.token:
            self.token = self.make_token()
        super().save(*args, **kwargs)


    def rotate_token(self):
        """
        Issue a new secret. Every previously printed copy of this QR
        keeps identifying the badge but fails the token check — the
        lost-badge response. Regenerate + reprint afterwards.
        """
        self.token = self.make_token()
        self.save(update_fields=["token"])

    def revoke(self):
        self.is_active = False
        self.save(update_fields=["is_active"])

    # ---------------- image generation ----------------

    def generate_qr(self, force=False, save_employee=True):
        """Generate (or regenerate) the QR image, save it to the linked
        Employee, and return its URL.

        ``force`` recreates even if an image already exists.
        ``save_employee`` controls whether the Employee is saved here;
        pass False to update the field yourself.

        Fixes over the original version, everything else unchanged:
          - encodes the stable /qr/<uuid>/?t=<token> scan URL from
            settings.QR_SCAN_ORIGIN — never get_absolute_url() (slug
            changes would orphan printed badges), never a request or
            127.0.0.1 fallback (signal-generated badges used to encode
            localhost)
          - no generate_token() call needed: save() guarantees a token
          - filename is the employee UUID (stable), not the slug
            (mutable)
          - settings imported from django.conf, not main
        """
        emp = self.employee
        if emp is None:
            return None

        if emp.qr_code_image and not force:
            return emp.qr_code_image.url
        if force and emp.qr_code_image:
            try:
                emp.qr_code_image.delete(save=False)
            except Exception:
                pass

        full_url = f"{settings.QR_SCAN_ORIGIN.rstrip('/')}/qr/{self.id}/?t={self.token}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=40,
            border=6,
        )
        qr.add_data(full_url)
        qr.make(fit=True)

        qr_img = qr.make_image(
            image_factory=StyledPilImage,
            module_drawer=CircleModuleDrawer(),
        ).convert("RGBA")

        logo_path = settings.BASE_DIR / "static" / "images" / "UoN CREST_new-01.png"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")

            qr_w, qr_h = qr_img.size
            max_logo_size = int(qr_w * 0.25)
            logo.thumbnail((max_logo_size, max_logo_size), Image.Resampling.LANCZOS)

            logo_w, logo_h = logo.size
            padding = 10
            bg = Image.new("RGBA", (logo_w + padding * 2, logo_h + padding * 2), "white")
            bg.paste(logo, (padding, padding), mask=logo.split()[-1])

            paste_x = (qr_w - bg.width) // 2
            paste_y = (qr_h - bg.height) // 2
            qr_img.paste(bg, (paste_x, paste_y), mask=bg.split()[-1])

        qr_bytes = BytesIO()
        try:
            qr_img.save(qr_bytes, format="PNG", dpi=(300, 300))
        except Exception:
            # PIL fileno quirk on some platforms — the data is fine.
            qr_img.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)

        emp.qr_code_image.save(f"{emp.pk}.png", File(qr_bytes), save=False)
        if save_employee:
            emp.save(update_fields=["qr_code_image"])
        return emp.qr_code_image.url
    
    
    def delete(self, *args, **kwargs):
            # The badge image lives on Employee (single-model fetch), so
            # deleting the credential must clear its picture too —
            # otherwise the profile page keeps showing a badge that no
            # longer exists (and scans UNKNOWN).
            emp = self.employee
            super().delete(*args, **kwargs)
            if emp and emp.qr_code_image:
                emp.qr_code_image.delete(save=True)




class ScanLog(models.Model):
    """
    One row per scan attempt, successful or not. The failed ones
    (revoked badge at a gate, forged token) are the interesting rows;
    the successful ones become analytics.
    """

    class Result(models.TextChoices):
        VALID = "VALID", "Valid"
        REVOKED = "REVOKED", "Revoked"
        EXPIRED = "EXPIRED", "Expired"
        BAD_TOKEN = "BAD_TOKEN", "Bad token"
        UNKNOWN = "UNKNOWN", "Unknown QR id"

    qrcode = models.ForeignKey(
        QRCode,
        on_delete=models.CASCADE,
        related_name="scans",
        blank=True,
        null=True,  # null when the scanned UUID matched nothing
    )
    scanned_at = models.DateTimeField(auto_now_add=True)
    result = models.CharField(max_length=10, choices=Result.choices)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["-scanned_at"]

    def __str__(self):
        return f"{self.qrcode or 'unknown'} @ {self.scanned_at:%Y-%m-%d %H:%M} → {self.result}"


class Supervisor(models.Model):
    """Grants a user CRUD rights over QR codes for one organisational
    unit — independent of whether they're an Employee in that unit
    themselves. Exactly one of department/service_unit/research_unit
    is set, same shape as Employee's own unit fields.

    A user can hold more than one Supervisor row to cover several
    units (e.g. one person temporarily covering two departments).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="qr_supervisor_roles",
        verbose_name="Supervisor",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="qr_supervisors",
    )
    service_unit = models.ForeignKey(
        ServiceUnit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="qr_supervisors",
    )
    research_unit = models.ForeignKey(
        ResearchUnit,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="qr_supervisors",
    )

    class Meta:
        verbose_name = "QR Supervisor"
        verbose_name_plural = "QR Supervisors"

    @property
    def unit(self):
        return self.department or self.service_unit or self.research_unit

    def clean(self):
        chosen = [u for u in (self.department, self.service_unit, self.research_unit) if u is not None]
        if len(chosen) != 1:
            raise ValidationError(
                "Choose exactly one of Department, Service Unit, or Research Unit."
            )

    def __str__(self):
        return f"{self.user} — {self.unit or 'no unit'}"

    @staticmethod
    def unit_q_for(user, prefix=""):
        """Q matching `prefix` to any unit `user` supervises, or False
        if they supervise nothing. `prefix` lets this filter both
        Employee querysets (prefix="") and QRCode querysets
        (prefix="employee__")."""
        q = None
        for role in Supervisor.objects.filter(user=user):
            if role.department_id:
                part = Q(**{f"{prefix}department_id": role.department_id})
            elif role.service_unit_id:
                part = Q(**{f"{prefix}service_unit_id": role.service_unit_id})
            elif role.research_unit_id:
                part = Q(**{f"{prefix}research_unit_id": role.research_unit_id})
            else:
                continue
            q = part if q is None else (q | part)
        return q if q is not None else False