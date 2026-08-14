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

from apps.home.models import Banner, Department
from apps.staff.models import Employee, ResearchUnit, ServiceUnit


def _qr_watermark_image(is_alumni):
    """The crest pasted into the center of a generated QR code --
    admin-editable via Banner.staff_qr_watermark/alumni_qr_watermark
    (2026-08-14), not hardcoded, falling back to the original static
    file so nothing changes until an admin uploads a replacement. Reads
    through the field's storage API (.open()/.read()), not .path --
    Banner images are Cloudinary-backed in production, which has no
    local filesystem path (same reasoning as apps/staff/views.py's
    download_staff_qr_code)."""
    field_name = "alumni_qr_watermark" if is_alumni else "staff_qr_watermark"
    default_path = settings.BASE_DIR / "static" / "images" / (
        "UONAA Original Logo White.png" if is_alumni else "UoN CREST_new-01.png"
    )

    # Checked in Python via truthiness, not a DB .exclude(field="")
    # filter -- an existing Banner row predating this field has NULL
    # there, and NULL != '' is unknown (neither excluded nor matched)
    # under SQL's three-valued logic, so that filter alone let an unset
    # NULL row through as if it were "set". FieldFile's __bool__ checks
    # self.name, which is falsy for both NULL and '' -- same safe
    # pattern already used in apps/home/context_processors.py's
    # _first_image_url.
    file = None
    for banner in Banner.objects.all():
        candidate = getattr(banner, field_name)
        if candidate:
            file = candidate
            break

    if file:
        file.open("rb")
        try:
            image = Image.open(file).convert("RGBA")
            image.load()  # decode fully before the field file closes below
        finally:
            file.close()
        return image

    if default_path.exists():
        return Image.open(default_path).convert("RGBA")
    return None


class QRCode(models.Model):
    """
    A scannable credential. The QR image encodes:

        <QR_SCAN_ORIGIN>/qr/<id>/?t=<token>

    - ``id`` (UUID) identifies the badge itself — independent of what
      it points at (employee or alumni profile today; visitor/event
      labels supported; any model later without changing the URL
      scheme).
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

    # Optional link to an alumnus (2026-08-14) -- the "Digital alumni ID
    # (QR)" advertised as a membership benefit (templates/home/
    # membership_categories.html's tier copy). Deliberately NOT
    # unit-scoped like Employee -- alumni have no department/service/
    # research unit, so QRCodeAdmin's Supervisor-based scoping (see
    # apps/qr_manager/admin.py's _object_in_scope) naturally leaves
    # alumni-linked codes superuser-only, the same treatment
    # visitor/event codes already get there.
    alumni_profile = models.OneToOneField(
        "home.AlumniProfile",
        on_delete=models.CASCADE,
        related_name="alumni_qrcode",
        blank=True,
        null=True,
    )

    # Human label for codes with no employee/alumni: visitor's name,
    # event name, contractor company — whatever identifies the holder.
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

    def clean(self):
        super().clean()
        if self.employee_id and self.alumni_profile_id:
            raise ValidationError("A QR code can be linked to an employee or an alumni profile, not both.")

    @property
    def holder(self):
        """Whichever model this code is linked to, or None for a bare
        label-only code (visitor/event passes)."""
        return self.employee or self.alumni_profile

    def __str__(self):
        holder = self.holder
        name = holder.user.profile.full_name if holder else (self.label or "unassigned")
        return f"{name} — {self.get_qr_type_display()}"

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

    @property
    def scan_url(self):
        """
        The exact URL encoded in the QR image (verify_scan) — reused
        wherever something needs to link to this badge the same way a
        camera scan would (e.g. a tap-to-open link in the printable
        PDF), so it goes through the same token check + ScanLog entry
        instead of bypassing straight to the profile.
        """
        return f"{settings.QR_SCAN_ORIGIN.rstrip('/')}/qr/{self.id}/?t={self.token}"

    # ---------------- image generation ----------------

    def generate_qr(self, force=False, save_holder=True):
        """Generate (or regenerate) the QR image, save it to the linked
        Employee or AlumniProfile (whichever this code is holder for),
        and return its URL.

        ``force`` recreates even if an image already exists.
        ``save_holder`` controls whether the holder is saved here; pass
        False to update the field yourself.

        Fixes over the original version, everything else unchanged:
          - encodes the stable /qr/<uuid>/?t=<token> scan URL from
            settings.QR_SCAN_ORIGIN — never get_absolute_url() (slug
            changes would orphan printed badges), never a request or
            127.0.0.1 fallback (signal-generated badges used to encode
            localhost)
          - no generate_token() call needed: save() guarantees a token
          - filename is the holder's UUID (stable), not the slug
            (mutable)
          - settings imported from django.conf, not main
        """
        holder = self.holder
        if holder is None:
            return None

        if holder.qr_code_image and not force:
            return holder.qr_code_image.url
        if force and holder.qr_code_image:
            try:
                holder.qr_code_image.delete(save=False)
            except Exception:
                pass

        full_url = self.scan_url

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

        # Watermark differs by holder (2026-08-14): staff carry the
        # university's own crest, alumni carry the Association's -- two
        # separate institutional marks, not one generic logo for both.
        logo = _qr_watermark_image(is_alumni=bool(self.alumni_profile_id))
        if logo is not None:
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

        holder.qr_code_image.save(f"{holder.pk}.png", File(qr_bytes), save=False)
        if save_holder:
            holder.save(update_fields=["qr_code_image"])
        return holder.qr_code_image.url


    def delete(self, *args, **kwargs):
            # The badge image lives on the holder (single-model fetch), so
            # deleting the credential must clear its picture too —
            # otherwise the profile page keeps showing a badge that no
            # longer exists (and scans UNKNOWN).
            holder = self.holder
            super().delete(*args, **kwargs)
            if holder and holder.qr_code_image:
                holder.qr_code_image.delete(save=True)




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