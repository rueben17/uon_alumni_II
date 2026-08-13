from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from cloudinary_storage.storage import RawMediaCloudinaryStorage
from django_resized import ResizedImageField
from autoslug import AutoSlugField
from shortuuid.django_fields import ShortUUIDField
import uuid
from django.utils.text import slugify
from django.urls import reverse
from django.utils.timezone import now
from django.utils import timezone
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
import random
import string
from datetime import datetime
from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from phonenumber_field.modelfields import PhoneNumberField

from apps.user.models import Honorific

User = get_user_model()
# Create your models here.


# -------------------------------------------------------------------
# Faculty, Department -- moved from apps.staff.models (2026-08-06).
# Academic/institutional structure, not a staff concept: AlumniProfile,
# Chapter, InMemoriam, Qualification (all here) and Student.faculty were
# always the heavier consumers than apps.staff, which only ever reached
# Faculty transitively through Department. apps.staff.Employee.department
# and apps.staff.ResearchUnit.parent_faculty now FK here cross-app
# ('home.Department' / 'home.Faculty'). See docs/todo.md.
# -------------------------------------------------------------------

def get_department_slug(instance):
    return slugify(f"{instance.faculty.faculty_name} {instance.name}")


class Faculty(models.Model):
    faculty_name = models.CharField(
        max_length=255,
        unique=True,
        verbose_name=_("Faculty Name"),
        help_text=_("Official name of the faculty (e.g., 'Agriculture')"),
    )
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    slug = AutoSlugField(
        populate_from="faculty_name",
        unique=True,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
        verbose_name=_("Slug"),
    )

    class Meta:
        ordering = ["faculty_name"]
        verbose_name = _("Faculty")
        verbose_name_plural = _("Faculties")

    def __str__(self):
        return self.faculty_name


class Department(models.Model):
    name = models.CharField(max_length=255, verbose_name=_("Department Name"))
    faculty = models.ForeignKey(
        Faculty,
        on_delete=models.CASCADE,
        related_name="departments",
        verbose_name=_("Faculty"),
    )
    slug = AutoSlugField(
        populate_from=get_department_slug,
        unique=True,
        editable=True,
        always_update=True,
        null=True,
        verbose_name=_("Slug"),
    )
    description = models.TextField(blank=True, null=True)

    class Meta:
        unique_together = ("name", "faculty")
        ordering = ["name"]
        verbose_name = _("Department")
        verbose_name_plural = _("Departments")

    def __str__(self):
        return f"{self.faculty.faculty_name} - {self.name}"


class Title(models.CharField):
    def __init__(self, *args, **kwargs):
        super(Title, self).__init__(*args, **kwargs)

    def get_prep_value(self, value):
        return str(value).title()


class ThumbnailMixin(models.Model):
    """Shared `get_thumbnail()` for every content model with a single
    image field. Replaces six copy-pasted get_thumbnail/make_thumbnail/
    get_avatar/make_avatar implementations (Article, Event, Chapter,
    Partner, Executive, Secretariat).

    The old per-model `make_thumbnail()` was dead code in all of them:
    `if self.thumbnail: ...  else: if self.thumbnail: <call
    make_thumbnail>` -- that inner check is the same test as the outer
    one, inside the branch where it's already known false, so it could
    never run. Dropped rather than ported forward.

    Placeholder fixed too: the old fallback was a typo'd
    `via.placeholder.com/240x240x.jpg` (stray trailing "x"), a third
    party in the render path regardless.
    """

    thumbnail_field_name = "thumbnail"
    thumbnail_placeholder = "https://via.placeholder.com/240x240.jpg"

    class Meta:
        abstract = True

    def get_thumbnail(self):
        image = getattr(self, self.thumbnail_field_name)
        return image.url if image else self.thumbnail_placeholder


class Article(ThumbnailMixin, models.Model):

    class ArticleType(models.TextChoices):
        PAGE = "page", _("Standing Page")
        NEWS = "news", _("News")
        FEATURE = "feature", _("Feature")
        NOTICE = "notice", _("Notice")

    class PageKey(models.TextChoices):
        HISTORY = "history", _("History")
        DONATE = "donate", _("Donate")
        SCHOLARSHIP = "scholarship", _("Scholarship")
        CONTACT = "contact", _("Contact Us")
        CATEGORIES_BENEFITS = "categories-benefits", _("Categories & Benefits")
        ALUMNI_CARD = "alumni-card", _("Alumni Card")
        CORPORATES = "corporates", _("Corporates")
        NOTABLE_ALUMNI = "notable-alumni", _("Our Notable Alumni")
        AGM = "agm", _("Annual General Meeting")
        CONSULTANCY_TRAINING = "consultancy-training", _("Consultancy & Training")
        TERMS = "terms", _("Terms of Service")
        PRIVACY = "privacy", _("Privacy Policy")
        COOKIES = "cookies", _("Cookie Policy")
        SHOP = "shop", _("Shop")

    type = models.CharField(
        max_length=20,
        choices=ArticleType.choices,
        default=ArticleType.NEWS,
        verbose_name=_("Type"),
        help_text=_(
            "'Standing Page' + a Page Key below makes this the admin-editable "
            "copy for a fixed site page (History, Donate, ...). Everything "
            "else is ordinary published content."
        ),
    )
    # unique=True + null=True (not blank default '') is what guarantees at
    # most one Article per standing page at the DB level -- Postgres treats
    # multiple NULLs as distinct, so non-page articles (null) never collide,
    # while two 'history' rows would.
    page_key = models.CharField(
        max_length=20,
        choices=PageKey.choices,
        unique=True,
        null=True,
        blank=True,
        verbose_name=_("Page Key"),
        help_text=_("Set only for Type='Standing Page'. Fetch pages by this, never by slug."),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='articles')
    chapter = models.ForeignKey('Chapter', on_delete=models.CASCADE, related_name="articles",  blank=True, null=True)
    title =  Title(_("Title"), help_text=_("Required"), max_length=250)
    body = models.TextField()
    quote = models.TextField(max_length=1000,  blank=True, null=True)
    thumbnail = ResizedImageField(size=[1600, 1600], quality=85,
                        upload_to='articles/images/', blank=True, null=True)
    article_banner_image = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='articles/banners/', blank=True, null=True)
    created_at = models.DateTimeField(verbose_name=_("Created at"), default=timezone.now, blank=True)
    date_updated = models.DateTimeField(auto_now=True, verbose_name="date updated", blank=True)
    slug = AutoSlugField(populate_from='title',
                        unique_with=['created_at', ],
                        editable=True, always_update=False)
    is_feature = models.BooleanField(default=False)
    is_highlighted = models.BooleanField(default=False)

    # Draft/publish/schedule. Default True keeps today's "saving publishes
    # instantly" behaviour for anyone who ignores the field; unchecking it
    # is what lets an editor draft next month's news without it going live.
    is_published = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)


    def __str__(self):
        return f"{self.title}: {self.created_at}"


    class Meta:
        ordering = ['-created_at']
        unique_together = ('title', 'created_at')

    def save(self, *args, **kwargs):
        # Stamp published_at the first time this goes live -- never
        # overwritten on later edits, so it stays "when this was first
        # published," not "when it was last saved."
        if self.is_published and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("home:uon_alumni_article_detail", args=[self.slug])

    def get_article_banner_image(self):
        """Return the URL for the article banner image or a placeholder."""
        if self.article_banner_image:
            return self.article_banner_image.url
        return 'https://via.placeholder.com/1500x625.jpg'



class Banner(models.Model):
    text = models.CharField(
        verbose_name=_("Descriptive text"),
        help_text=_("Please add a short text about the banner "),
        max_length=75,
        null=True,
        blank=True,
    )
    top_banner = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='banner/top_banner/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)
    middle_banner = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='banner/middle_banner/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)

    bottom_banner = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='banner/bottom_banner/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)

    image = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='banner/image/%Y/%m/%d/',
                        help_text=_("Upload banner images "), blank=True, null=True)
    logo = ResizedImageField(size=[500, 500], quality=90,
                        upload_to='banner/logo/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = _("Banner Image")
        verbose_name_plural = _("Banner Images")


    def __str__(self):
        return f"{self.text}: {self.created_at}"



class Images(models.Model):
    """Multi-image gallery, one row per photo. Kept separate from each
    model's own single named image field (thumbnail/cover/photo) rather
    than replacing them (todo.md 0.3b: 'Do NOT fold the singular images
    into Images' -- a named field is the only thing guaranteeing exactly
    one thumbnail; this FK-per-model shape is deliberately not a single
    generic FK, for the same reason -- one more column here is cheaper
    than a `role` discriminator that re-invents the field name as
    unvalidated data)."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="images",  blank=True, null=True)
    chapter = models.ForeignKey('Chapter', on_delete=models.CASCADE, related_name="images",  blank=True, null=True)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name="images",  blank=True, null=True)
    publication = models.ForeignKey('Publication', on_delete=models.CASCADE, related_name="images", blank=True, null=True)
    in_memoriam = models.ForeignKey('InMemoriam', on_delete=models.CASCADE, related_name="images", blank=True, null=True)
    image = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='gallery/image-uploads',
                        help_text=_("Upload your image "),
                        blank=True, null=True)

    alt_text = models.CharField(
                    verbose_name=_("Alternative text"),
                    help_text=_("Please add a short alternative about the image"),
                    max_length=100,
                    null=True,
                    blank=True,
                )
    # Homepage advert/promo carousel (2026-08-11), below the banner --
    # these rows have no article/chapter/event/publication/in_memoriam
    # parent (an "unattached" image, per __str__ below), so a plain flag
    # is enough; no new FK needed since there's nothing model-specific to
    # point at.
    show_in_carousel = models.BooleanField(
        default=False,
        verbose_name=_("Show in homepage carousel"),
        help_text=_("Feature this image in the advert/promo carousel below the homepage banner."),
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = _("Gallery Image")
        verbose_name_plural = _("Gallery Images")


    def __str__(self):
        parent = self.article or self.chapter or self.event or self.publication or self.in_memoriam
        if parent is None:
            return f"Unattached image: {self.created_at}"
        label = self.alt_text[:30] if self.alt_text else ""
        return f"{parent}: {label}"




class CoreValue(models.Model):
    """
    Model representing an organization's core value
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField()
    svg_path = models.TextField(  # Changed from CharField to TextField
        blank=True, 
        help_text="SVG path data for the icon"
    )
    order = models.PositiveIntegerField(default=0, help_text="Display order")
    is_active = models.BooleanField(default=True)
    
    # For background image per value
    background_image = ResizedImageField(
        size=[2200, 2200], quality=85,
        upload_to='core_values/bg/',
        blank=True,
        null=True,
        help_text="Background image for this core value"
    )
    background_color = models.CharField(
        max_length=20, 
        default='#ffffff',
        help_text="Fallback background color (hex code)"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['order', 'name']
        verbose_name = "Core Value"
        verbose_name_plural = "Core Values"
    
    def __str__(self):
        return self.name
    
    def get_absolute_url(self):
        return reverse('core_value_detail', kwargs={'pk': self.pk})




class Executive(ThumbnailMixin, models.Model):

    thumbnail_field_name = "avatar"

    TITLE = (
        ('DR.', 'DR.'),
        ('ESQ.', 'ESQ.'),
        ('HON.', 'HON.'),
        ('ESQ.', 'ESQ.'),
        ('HON.', 'HON.'),
        ('MR.', 'MR.'),
        ('MRS.', 'MRS.'),
        ('Ms.', 'Ms.'),
        ('PROF.', 'PROF.'),
        ('REV.', 'REV.'),
        ('Rt. Hon.', 'Rt. Hon.'),
        ('SR.', 'SR.'),
    )

    EXECUTIVE_POSITION = (
        ('CHAIRMAN', 'CHAIRMAN'),
        ('VICE CHAIR', 'VICE CHAIR'),
        ('SECRETARY', 'SECRETARY'),
        ('DEPUTY SECRETARY', 'DEPUTY SECRETARY'),
        ('ORGANISING SECRETARY', 'ORGANISING SECRETARY'),
        ('DEPUTY ORGANISING SECRETARY', 'DEPUTY ORGANISING SECRETARY'),
        ('TREASURER', 'TREASURER'),
        ('DEPUTY TREASURER', 'DEPUTY TREASURER'),
        ('EDITOR', 'EDITOR'),
    )

    RANK = (
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
        ('6', '6'),
        ('7', '7'),
        ('8', '8'),
        ('9', '9'),
        ('10', '10'),
    )

    title =  models.CharField(max_length=10, choices=TITLE, )
    position = models.CharField(_('Executive Committee Position'), help_text=_(" Executive Committee Position"), max_length=255, choices=EXECUTIVE_POSITION, null=True, blank=True)
    rank = models.CharField(_('Executive Committee Rank'), help_text=_(" Executive Rank"), max_length=255, choices=RANK, null=True, blank=True)
    first_name = models.CharField(_('First Name'), max_length=150, blank=True)
    middle_name = models.CharField(_('Middle Name'), max_length=150, blank=True)
    surname = models.CharField(_('Surname'), max_length=150, blank=True)
    bio = models.TextField(_("Bio"), max_length=2500, blank=True, null=True)
    avatar = ResizedImageField(size=[1200, 1200], quality=85, upload_to='gallery/executive/', blank=True, null=True)


    class Meta:
        verbose_name = _("Executive")
        verbose_name_plural = _("Executive")


    def __str__(self):
        return f"{self.position}: {self.title}. {self.surname}"

    # "Avatar" reads more naturally than "thumbnail" for a person's photo.
    get_avatar = ThumbnailMixin.get_thumbnail



class Event(ThumbnailMixin, models.Model):
    """Something that *happens* at a time -- as opposed to Article, which
    is something *published* at a time. `event_type` absorbs
    workshop/conference/forum/training, moved off Article's own type
    field (todo.md 0.3b): Article.created_at was the wrong axis for
    scheduling, and Phase 4 RSVPs hang off this model, not Article."""

    class EventType(models.TextChoices):
        WALK = "walk", _("Alumni Walk")
        WORKSHOP = "workshop", _("Workshop")
        CONFERENCE = "conference", _("Conference")
        FORUM = "forum", _("Forum")
        TRAINING = "training", _("Training")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=20, choices=EventType.choices, default=EventType.WALK)
    title =  Title(_("Title"), help_text=_("Required"), max_length=250)
    body = models.TextField()
    thumbnail = ResizedImageField(size=[2200, 2200], quality=85,
                        upload_to='walk/images/',
                        blank=True, null=True)
    created_at = models.DateTimeField(verbose_name=_("Created at"), default=timezone.now, blank=True)
    date_updated = models.DateTimeField(auto_now=True, verbose_name="date updated", blank=True)
    slug = AutoSlugField(populate_from='title',
                        unique_with=['created_at', ],
                        editable=True, always_update=False)



    def __str__(self):
        return f"{self.title}: {self.created_at}"


    class Meta:
        ordering = ['-created_at']
        unique_together = ('title', 'created_at')


    def get_absolute_url(self):
        return reverse("home:uon_alumni_walk_detail", args=[self.slug])



class Chapter(ThumbnailMixin, models.Model):
    faculty = models.ForeignKey(Faculty, related_name='chapters', on_delete=models.CASCADE, blank=True, null=True)
    name = models.CharField(max_length=100)
    about = models.TextField(blank=True, null=True)
    year_launched = models.DateTimeField(verbose_name=_("Launched On "),  blank=True, null=True)
    slug = AutoSlugField(populate_from='name',
                         unique_with=['year_launched', ],
                         editable=True, always_update=False, blank=True, null=True)
    thumbnail = ResizedImageField(size=[1600, 1600], quality=85,
                        upload_to='chapter/uploads/%Y/%m/%d/',
                        help_text=_("Chapter banner "),
                        blank=True, null=True)


    class Meta:
        verbose_name = _('Chapter')
        verbose_name_plural = _("Chapters")


    def __str__(self):
        return f"{self.name}"


    def get_absolute_url(self):
        if self.faculty:
            faculty_slug = slugify(self.faculty.faculty_name)
            return reverse("home:uon_alumni_chapter_detail", args=[faculty_slug, self.slug])
        return reverse("home:uon_alumni_chapter_detail", args=[self.slug])


class Partner(ThumbnailMixin, models.Model):
    title =  Title(_("Title"), help_text=_("Required"), max_length=250)
    relation = models.CharField(
                    verbose_name=_("Partner Relation"),
                    help_text=_("Relation with UoNAA "),
                    max_length=125,
                    null=True,
                    blank=True,
                )
    thumbnail = ResizedImageField(size=[1600, 1600], quality=85,
                        upload_to='gallery/partners/',
                        blank=True, null=True)
    created_at = models.DateTimeField(verbose_name=_("Created at"), default=timezone.now, blank=True)

    def __str__(self):
        return f"{self.title}: {self.created_at}"


    class Meta:
        ordering = ['-created_at']
        unique_together = ('title', 'created_at')


class Secretariat(ThumbnailMixin, models.Model):

    TITLE = (
        ('DR.', 'DR.'),
        ('ESQ.', 'ESQ.'),
        ('HON.', 'HON.'),
        ('ESQ.', 'ESQ.'),
        ('HON.', 'HON.'),
        ('MR.', 'MR.'),
        ('MRS.', 'MRS.'),
        ('Ms.', 'Ms.'),
        ('PROF.', 'PROF.'),
        ('REV.', 'REV.'),
        ('Rt. Hon.', 'Rt. Hon.'),
        ('SR.', 'SR.'),
    )
    
    SECRETARIAT_POSITION = (
        ('EXECUTIVE DIRECTOR', 'EXECUTIVE DIRECTOR'),
        ('ASSISTANT ADMINISTRATOR', 'ASSISTANT ADMINISTRATOR'),
        ('SENIOR ICT OFFICER', 'SENIOR ICT OFFICER'),
        ('SECRETARY', 'SECRETARY'),
        ('EDITOR', 'EDITOR'),
    )

    RANK = (
        ('1', '1'),
        ('2', '2'),
        ('3', '3'),
        ('4', '4'),
        ('5', '5'),
        ('6', '6'),
        ('7', '7'),
        ('8', '8'),
        ('9', '9'),
        ('10', '10'),
    )

    thumbnail_field_name = "avatar"

    title =  models.CharField(max_length=10, choices=TITLE, )
    first_name = models.CharField(_('First Name'), max_length=150, blank=True)
    middle_name = models.CharField(_('Middle Name'), max_length=150, blank=True)
    surname = models.CharField(_('Surname'), max_length=150, blank=True)
    position = models.CharField(_('Secretariat Position'), help_text=_("Secretariat Position"), max_length=255, choices=SECRETARIAT_POSITION, null=True, blank=True)
    rank = models.CharField(_('Secretariat Rank'), help_text=_("Secretariat Rank"), max_length=255, choices=RANK, null=True, blank=True)
    bio = models.TextField(_("Bio"), max_length=2500, blank=True, null=True)
    avatar = ResizedImageField(size=[1200, 1200], quality=85, upload_to='gallery/secretariat/', blank=True, null=True)


    class Meta:
        verbose_name = _("Secretariat")
        verbose_name_plural = _("Secretariat")


    def __str__(self):
        return f"{self.position}: {self.title}. {self.surname}"

    # "Avatar" reads more naturally than "thumbnail" for a person's photo.
    get_avatar = ThumbnailMixin.get_thumbnail


class Publication(models.Model):
    """Newsletters, committee minutes, annual reports, policies, financial
    statements, forms (todo.md 0.3b). `visibility=members` is the first
    membership benefit the system can actually deliver on day one --
    1.6's other benefits are physical (card/cert/badge) or aspirational."""

    class Category(models.TextChoices):
        NEWSLETTER = "newsletter", _("Newsletter")
        MINUTES = "minutes", _("Committee Minutes")
        ANNUAL_REPORT = "annual_report", _("Annual Report")
        POLICY = "policy", _("Policy")
        FINANCIAL_STATEMENT = "financial_statement", _("Financial Statement")
        FORM = "form", _("Form")

    class Visibility(models.TextChoices):
        PUBLIC = "public", _("Public")
        MEMBERS = "members", _("Members Only")
        COMMITTEE = "committee", _("Committee Only")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=30, choices=Category.choices)
    visibility = models.CharField(max_length=20, choices=Visibility.choices, default=Visibility.PUBLIC)
    # Meeting or issue date -- distinct from created_at (when it was uploaded).
    document_date = models.DateField()
    volume = models.CharField(max_length=20, blank=True)
    issue_number = models.CharField(max_length=20, blank=True)
    # Minutes exist as draft before being approved at the next meeting.
    is_approved = models.BooleanField(default=False)
    # NOT the default storage. DEFAULT_FILE_STORAGE is MediaCloudinaryStorage
    # in production (main/settings.py:286), which treats every upload as an
    # image and will mangle a PDF -- RawMediaCloudinaryStorage is the
    # correct one regardless of environment, not just here-and-now while
    # DEBUG happens to fall back to local filesystem. Local dev needs real
    # (or sandbox) Cloudinary credentials in .env for uploads to this field
    # to actually work -- verify before building UI on top (todo.md 0.3b).
    file = models.FileField(upload_to='publications/%Y/%m/', storage=RawMediaCloudinaryStorage)
    cover_image = ResizedImageField(size=[1600, 1600], quality=85, upload_to='publications/covers/', blank=True, null=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='publications'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-document_date']
        verbose_name = _("Publication")
        verbose_name_plural = _("Publications")

    def __str__(self):
        return f"{self.title} ({self.get_category_display()})"


class InMemoriam(models.Model):
    """A person registry, not article bodies -- as free text you could
    never list alphabetically, show a photo grid, or filter by year
    (todo.md 0.3b). Reuses apps.user.models.Honorific rather than
    inventing a fifth title vocabulary (todo.md's own guiding decision:
    'One Honorific TextChoices ... replaces all four existing title
    vocabularies')."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    honorific = models.CharField(max_length=10, choices=Honorific.choices, blank=True)
    given_name = models.CharField(max_length=150)
    family_name = models.CharField(max_length=150)
    birth_year = models.PositiveIntegerField(null=True, blank=True)
    death_year = models.PositiveIntegerField(null=True, blank=True)
    graduation_year = models.PositiveIntegerField(null=True, blank=True)
    faculty = models.ForeignKey(
        Faculty, on_delete=models.SET_NULL, null=True, blank=True, related_name='in_memoriam_entries'
    )
    photo = ResizedImageField(size=[1200, 1200], quality=85, upload_to='in_memoriam/', blank=True, null=True)
    tribute = models.TextField(blank=True)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['family_name', 'given_name']
        verbose_name = _("In Memoriam Entry")
        verbose_name_plural = _("In Memoriam")

    def __str__(self):
        if self.birth_year and self.death_year:
            return f"{self.given_name} {self.family_name} ({self.birth_year}–{self.death_year})"
        return f"{self.given_name} {self.family_name}"


class JobPosting(models.Model):
    """Members-only, moderated, with an expiry date. 1.6 sells
    'internship/job access via the network' as the student tier's
    *primary* draw and nothing currently delivers it (todo.md 0.3b) --
    either this gets built and routed, or the Association stops
    advertising it (see todo.md C.7)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField()
    application_url = models.URLField(blank=True)
    application_email = models.EmailField(blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='job_postings'
    )
    # Moderated -- visible only once a Secretariat member approves it.
    is_approved = models.BooleanField(default=False)
    expires_on = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Job Posting")
        verbose_name_plural = _("Job Postings")

    def __str__(self):
        return f"{self.title} @ {self.company}"

    @property
    def is_live(self):
        return self.is_approved and self.expires_on >= timezone.now().date()


class ContactMessage(models.Model):
    """Persisted regardless of whether email delivery succeeds (todo.md
    C.1: 'A contact page that silently discards messages is worse than
    none'). EMAIL_BACKEND isn't configured yet (no SMTP settings in
    main/settings.py) -- this row is what guarantees the message survives
    that, not the best-effort notification email sent alongside it."""

    name = models.CharField(max_length=150)
    email = models.EmailField()
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = _("Contact Message")
        verbose_name_plural = _("Contact Messages")

    def __str__(self):
        return f"{self.name} <{self.email}>: {self.subject or self.message[:40]}"


class MembershipTier(models.Model):
    TIER_TYPES = [
        ('life', 'Life Member'),
        ('annual', 'Annual Member'),
        ('honorary', 'Honorary Member'),
        ('corporate', 'Corporate Partner'),
        ('student', 'Student Member'),
        # Free entry-level tier (2026-08-10) -- distinct from 'student',
        # which specifically means enrolled-student status; Registered is
        # anyone who signed up without paying anything.
        ('registered', 'Registered Member'),
    ]
    name = models.CharField(max_length=50)  # "Gold Life Member"
    fee = models.DecimalField(max_digits=10, decimal_places=2)
    tier_type = models.CharField(max_length=20, choices=TIER_TYPES)
    duration_months = models.IntegerField(default=0, help_text="0 = lifetime")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)  # for display order
    # Monotonic upgrade path (todo.md 0.1: Annual -> Bronze -> Silver ->
    # Gold -> Corporate). Null = off the ladder (e.g. Honorary, Student).
    # Phase 2.6's installment upgrades resolve "the next rung's price" off
    # this -- `order` is display-only and can't carry that.
    ladder_rank = models.PositiveSmallIntegerField(null=True, blank=True)

    # M-Pesa eligibility (Association decision 2026-08-07): "up to Gold"
    # implemented as fee <= this ceiling, not ladder_rank <= Gold's rank --
    # ladder_rank is null for Honorary/Student (cheaper than Gold, should
    # still get M-Pesa) and for Platinum/Diamond (off-ladder but pricier
    # than Gold, so correctly excluded here regardless of their still-open
    # ladder placement -- see todo.md). Also lines up with M-Pesa's real
    # per-transaction limit in Kenya, which makes Corporate/Platinum/
    # Diamond-sized fees impractical over M-Pesa regardless of policy.
    MPESA_FEE_CEILING = Decimal("100000.00")

    def __str__(self):
        return f"{self.name} - KES {self.fee}"

    @property
    def allows_mpesa(self):
        return self.fee <= self.MPESA_FEE_CEILING

    @property
    def is_corporate(self):
        """Derived, not stored (2026-08-10) -- "no field lives in two
        places" (docs/todo.md's governing rule). tier_type already carries
        this; a separate boolean could only ever agree with it or drift
        from it."""
        return self.tier_type == "corporate"

    @property
    def track(self):
        """student / individual / corporate -- derived from tier_type for
        the same reason as is_corporate above. Distinct from tier_type
        itself (which has 6 values); this collapses them to the three
        tracks the 2026-08-10 tier-audit's rules describe."""
        if self.tier_type == "student":
            return "student"
        if self.tier_type == "corporate":
            return "corporate"
        return "individual"

    @property
    def billing_period(self):
        """free / annual / one_off, derived rather than stored for the
        same reason as is_corporate above -- fully determined by fee and
        is_lifetime() already. free beats one_off in priority: Registered
        is fee=0 but not literally on the lifetime/Life-tier code path
        (tier_type != 'life'), so is_lifetime() would say False for it --
        checking fee first, always, is what actually makes it read as
        'free' rather than 'annual' for a zero-fee tier of any duration.
        """
        if self.fee == 0:
            return "free"
        if self.is_lifetime():
            return "one_off"
        return "annual"

    def is_lifetime(self):
        """Check if this tier is a lifetime membership"""
        return self.tier_type == 'life' or self.duration_months == 0
    
    def get_expiry_date(self, start_date=None):
        """Calculate expiry date based on tier duration.

        Uses relativedelta, not timedelta(days=months*30) -- the old
        30-days-per-month approximation turned "12 months" into 360 days,
        so every renewal landed ~5-6 days earlier than the true calendar
        anniversary and the drift compounded release over release
        (todo.md 0.3, fixed 2026-08-10). relativedelta adds real calendar
        months, so a join date of e.g. Feb 29 on a leap year still lands
        on a sane date the next non-leap year (Feb 28), which a raw
        day-count can't express either.
        """
        if start_date is None:
            start_date = timezone.now().date()

        if self.is_lifetime():
            return None  # Never expires

        return start_date + relativedelta(months=self.duration_months)


class Benefit(models.Model):
    """A named perk that may or may not apply to a given MembershipTier --
    the per-tier value lives on TierBenefit below, not here (docs/todo.md
    1.6). Every real benefit maps to one of four axes; anything that
    doesn't is marketing copy, not a benefit (2026-08-10 UX/UI spec)."""

    class Axis(models.TextChoices):
        ACCESS = "access", _("Access")       # physically scarce, verifiable at a gate
        VOICE = "voice", _("Voice")           # binary and enforceable (candidacy, seats)
        ECONOMIC = "economic", _("Economic")  # members earn from it
        LEGACY = "legacy", _("Legacy")        # permanent and named

    name = models.CharField(max_length=255)
    axis = models.CharField(max_length=20, choices=Axis.choices)
    description = models.TextField(blank=True, default="")
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]
        verbose_name = _("Benefit")
        verbose_name_plural = _("Benefits")

    def __str__(self):
        return self.name


class TierBenefit(models.Model):
    """One cell of the tier x benefit matrix -- status is never boolean
    (a cell can be included, excluded, not applicable, or included with a
    qualifier like "2 vehicles" or "25% off", hence `detail` alongside
    `status` rather than a plain BooleanField)."""

    class Status(models.TextChoices):
        INCLUDED = "included", _("Included")
        EXCLUDED = "excluded", _("Excluded")
        NOT_APPLICABLE = "not_applicable", _("Not applicable")

    tier = models.ForeignKey(MembershipTier, on_delete=models.CASCADE, related_name="tier_benefits")
    benefit = models.ForeignKey(Benefit, on_delete=models.CASCADE, related_name="tier_benefits")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.EXCLUDED)
    detail = models.CharField(
        max_length=255, blank=True, default="",
        help_text=_("Qualifier for an included benefit, e.g. \"2 vehicles\", \"25% off\", \"eligible\". Leave blank for a plain ✓."),
    )
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("tier", "benefit")
        ordering = ["display_order"]
        verbose_name = _("Tier Benefit")
        verbose_name_plural = _("Tier Benefits")

    def __str__(self):
        detail_suffix = f" ({self.detail})" if self.detail else ""
        return f"{self.tier.name} — {self.benefit.name}: {self.get_status_display()}{detail_suffix}"


def get_alumni_profile_slug(instance):
    """Reads through UserProfile, same pattern as apps/staff/models.py's
    get_employee_slug — AlumniProfile no longer holds name data itself
    (docs/rebuild-schema.md)."""
    profile = instance.user.profile
    return slugify(f"{profile.honorific} {profile.given_name} {profile.family_name}")


class QualificationLevel(models.TextChoices):
    PHD = "phd", _("Doctor of Philosophy (PhD)")
    MASTERS = "masters", _("Master's Degree")
    BACHELORS = "bachelors", _("Bachelor's Degree")
    PGD = "pgd", _("Postgraduate Diploma")
    DIPLOMA = "diploma", _("Diploma")
    FELLOWSHIP = "fellowship", _("Fellowship")


class Qualification(models.Model):
    """
    UoN degrees/diplomas/certificates conferred, as listed in the official
    congregation booklet -- seeded via seed_qualifications management command.
    """
    faculty = models.ForeignKey(Faculty, on_delete=models.CASCADE, related_name='qualifications')
    level = models.CharField(max_length=20, choices=QualificationLevel.choices)
    name = models.CharField(max_length=255)

    class Meta:
        unique_together = ('faculty', 'name')
        ordering = ['faculty__faculty_name', 'level', 'name']
        verbose_name = _("Qualification")
        verbose_name_plural = _("Qualifications")

    def __str__(self):
        return f"{self.name} ({self.faculty.faculty_name})"


class AlumniProfile(models.Model):
    """Academic and external-employment data only. Personal data lives on
    UserProfile; membership data lives on Membership (both split out per
    docs/rebuild-schema.md, D3 in docs/0.1-identity-decisions.md)."""

    class GraduationInstitution(models.TextChoices):
        UON = "uon", _("University of Nairobi (Alumni)")
        OTHER = "other", _("Other Institution")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Link to Django User (One-to-One)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='alumni_profile')

    # Alumni specific
    graduation_year = models.IntegerField(null=True, blank=True)
    faculty = models.ForeignKey(Faculty, on_delete=models.SET_NULL, null=True, blank=True)
    # Reg-no source for alumni who register directly and never had a
    # Student row (everyone pre-dating the system). Students who came
    # through apps.student.models.Student have it there instead.
    student_reg_no = models.CharField(max_length=50, blank=True)
    graduation_institution = models.CharField(max_length=10, choices=GraduationInstitution.choices, blank=True, default="")
    other_institution_name = models.CharField(max_length=255, blank=True, default="")
    other_institution_qualification = models.CharField(max_length=255, blank=True, default="")
    name_at_graduation = models.CharField(max_length=300, blank=True, default="", help_text=_("Only if different from your current name"))
    qualification = models.ForeignKey(Qualification, on_delete=models.SET_NULL, null=True, blank=True, related_name='alumni')
    # Free-text fallback when `qualification` doesn't resolve to a seeded
    # Qualification row (2026-08-07) -- e.g. legacy import course names
    # that don't match the catalog ("BDS MPH" is two combined degrees) or
    # predate it entirely. Mirrors AlumniQualification.course_name_raw's
    # same fallback for the overflow (2nd/3rd) degree slots; this was the
    # one gap left when that was built -- the PRIMARY slot had no raw-text
    # fallback, so an unmatched primary course was silently lost on
    # import. Not shown on the self-service registration/edit forms --
    # alumni pick a real Qualification via the cascading dropdown there;
    # this is for historical data preservation, not new data entry.
    qualification_name_raw = models.CharField(max_length=255, blank=True, default="")

    # Employment (external -- distinct from apps.staff.Employee, which is
    # the internal UoN appointment; a staff-alumnus legitimately has both)
    current_employer = models.CharField(max_length=255, blank=True, default="")
    employment_position = models.CharField(max_length=255, blank=True, default="")

    # Meta
    registration_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    slug = AutoSlugField(
        populate_from=get_alumni_profile_slug,
        unique=False,
        editable=True,
        always_update=True,
        blank=True,
        null=True,
    )

    def __str__(self):
        return self.user.profile.full_name

    def get_absolute_url(self):
        # Explicit urlconf: this is called from the shared navbar context
        # processor, which runs on every subdomain -- without pinning it,
        # reverse() would use whatever urlconf is active for the CURRENT
        # request (e.g. apps.staff.site_urls on the staff subdomain, which
        # has no 'home' namespace at all) instead of always resolving
        # against the urlconf that actually defines this URL.
        return reverse(
            "home:alumni_detail",
            kwargs={"slug": self.slug, "pk": self.pk},
            urlconf="main.urls",
        )

    def get_edit_url(self):
        return reverse(
            "home:alumni_profile_update",
            kwargs={"slug": self.slug, "pk": self.pk},
            urlconf="main.urls",
        )

    def get_membership_update_url(self):
        return reverse(
            "home:alumni_membership_update",
            kwargs={"slug": self.slug, "pk": self.pk},
            urlconf="main.urls",
        )

    def get_delete_url(self):
        return reverse(
            "home:alumni_profile_delete",
            kwargs={"slug": self.slug, "pk": self.pk},
            urlconf="main.urls",
        )


class AlumniQualification(models.Model):
    """A degree/diploma beyond the primary one already on AlumniProfile
    (graduation_year/faculty/qualification). Purely additive: the legacy
    Google Forms membership register captured up to three College+Faculty+
    Course+Graduation sets per person (one alumnus can hold a UoN Bachelor's
    AND a UoN Master's, for instance), and AlumniProfile was built assuming
    one. Rather than touch the existing fields -- which every current
    template/form/admin screen already reads as "the" degree -- this table
    holds the overflow, and AlumniProfile's own fields keep meaning
    "primary" exactly as they do today.

    legacy_college is kept verbatim (e.g. "CHSS") purely as an import audit
    trail -- docs/uon_faculty_mapping.json is what actually resolves it to
    a current `faculty` FK, since the six legacy colleges were abolished in
    the 2021 restructure and no longer exist as rows anywhere."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alumni_profile = models.ForeignKey(
        AlumniProfile, on_delete=models.CASCADE, related_name="additional_qualifications"
    )
    order = models.PositiveSmallIntegerField(default=1)
    legacy_college = models.CharField(max_length=100, blank=True, default="")
    faculty = models.ForeignKey(Faculty, on_delete=models.SET_NULL, null=True, blank=True)
    qualification = models.ForeignKey(
        Qualification, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Free-text fallback for legacy course names that don't resolve to a
    # seeded Qualification row (decades of naming drift) -- never silently
    # dropped just because it doesn't match.
    course_name_raw = models.CharField(max_length=255, blank=True, default="")
    graduation_year = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["alumni_profile", "order"]
        verbose_name = _("Additional Qualification")
        verbose_name_plural = _("Additional Qualifications")

    def __str__(self):
        label = self.qualification.name if self.qualification else self.course_name_raw
        return f"{self.alumni_profile} — {label or 'Qualification'} ({self.graduation_year or 'n/d'})"


class AlumniEmploymentRecord(models.Model):
    """Employment beyond AlumniProfile's primary current_employer/
    employment_position -- same overflow pattern as AlumniQualification,
    for the legacy form's Position1/Organization1 columns."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    alumni_profile = models.ForeignKey(
        AlumniProfile, on_delete=models.CASCADE, related_name="employment_history"
    )
    order = models.PositiveSmallIntegerField(default=1)
    organization = models.CharField(max_length=255, blank=True, default="")
    position = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        ordering = ["alumni_profile", "order"]
        verbose_name = _("Additional Employment Record")
        verbose_name_plural = _("Additional Employment Records")

    def __str__(self):
        return f"{self.alumni_profile} — {self.position or 'Position'} at {self.organization or 'Organization'}"


class AlumniPhoneNumber(models.Model):
    """Phone numbers beyond User.phone (primary) and UserProfile.alt_phone
    -- the legacy form captured up to three (Telephone/Telephone1/
    Telephone2). FK's on User, not AlumniProfile: phone is a User-level
    handle everywhere else in this codebase (docs/rebuild-schema.md)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="additional_phones")
    phone = PhoneNumberField(region="KE")
    label = models.CharField(max_length=50, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user", "created_at"]
        verbose_name = _("Additional Phone Number")
        verbose_name_plural = _("Additional Phone Numbers")

    def __str__(self):
        return f"{self.user.email} — {self.phone}"


class MembershipManager(models.Manager):
    def current_for(self, user):
        """Most recent membership row for a user, active or otherwise --
        the manager method todo.md 0.1 asks for instead of a denormalized
        pointer. Ordered by Meta.ordering (-created_at), so "current"
        means "most recently requested," which is also "most recently
        activated" under the one-row-per-request pattern each request
        view uses (see apps/home/views.py)."""
        return self.filter(user=user).first()


class Membership(models.Model):
    """FK (not O2O) to User so history accumulates -- todo.md 1.4 wants
    renewal/upgrade history visible, and Phase 2.6's installment upgrades
    need a row to accumulate against. A free Student tier has no
    AlumniProfile to attach to (that's the whole reason this moved off
    AlumniProfile -- see D3 in docs/0.1-identity-decisions.md), so it
    anchors on User instead. "Current" membership is a manager method,
    never a denormalized pointer.

    Each renewal/upgrade request creates its own row, pending from the
    start (apps/home/views.py) -- PaymentAdmin.mark_completed() finds
    that row and calls activate() on it, rather than mutating one
    long-lived row in place. Simple enough to build tonight without
    guessing at the real Phase 1.3 service layer's shape (that still
    owns renew-in-place vs. new-row semantics, if they ever diverge from
    this)."""

    objects = MembershipManager()

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACTIVE = "active", _("Active")
        EXPIRED = "expired", _("Expired")
        CANCELLED = "cancelled", _("Cancelled")
        # A renewal/upgrade activated and replaced this row (1.3 service
        # layer, 2026-08-10) -- distinct from EXPIRED, which means the
        # member let it lapse with nothing replacing it. Lets "current
        # membership" stay a simple status filter instead of every call
        # site having to order-by-latest to find it.
        SUPERSEDED = "superseded", _("Superseded")

    class PaymentFrequency(models.TextChoices):
        ONCE = "once", _("Once")
        MONTHLY = "monthly", _("Monthly")
        QUARTERLY = "quarterly", _("Quarterly")
        ANNUALLY = "annually", _("Annually")

    # Grace period = one full billing cycle past the due date (miss two
    # installments in a row and it lapses), not a flat number of days --
    # a flat 30 days would be far too aggressive for an annual plan.
    # Association-adjustable; not a hard business rule handed down.
    INSTALLMENT_FREQUENCY_DAYS = {
        PaymentFrequency.MONTHLY: 30,
        PaymentFrequency.QUARTERLY: 90,
        PaymentFrequency.ANNUALLY: 365,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    tier = models.ForeignKey(MembershipTier, on_delete=models.PROTECT, related_name="memberships")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)

    started_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)  # null once active = lifetime
    is_lifetime = models.BooleanField(default=False)
    # NOT unique=True at the field level (2026-08-10, 1.3 service layer):
    # the ratified "membership_number carries forward across renewals"
    # decision means the outgoing (SUPERSEDED) row and the incoming
    # (ACTIVE) row briefly hold the SAME number -- a blanket unique
    # constraint makes that literally impossible to save. Uniqueness is
    # enforced instead by Meta.constraints, scoped to only ACTIVE rows --
    # exactly one row per number may be live at a time; history keeps its
    # number on superseded rows too.
    membership_number = models.CharField(max_length=20, null=True, blank=True)
    payment_frequency = models.CharField(max_length=20, choices=PaymentFrequency.choices, default=PaymentFrequency.ONCE)

    # What was actually paid for *this* row -- deliberately separate from
    # tier.fee, which is the CURRENT list price and drifts over time.
    # Without this, "total subscriptions collected by year/tier" can't be
    # reconstructed once fees change. Backs the planned Chart.js/Highcharts
    # membership analytics (subscriptions, tiers, faculties -- todo.md).
    subscription_amount = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text=_("Amount actually paid/subscribed for this membership row. "
                    "May differ from the tier's current fee."),
    )

    # Installment plans (2026-08-07): payment_frequency above was already on
    # the model but unused until now. A plan is just payment_frequency !=
    # ONCE -- no separate boolean, no fixed installment count/amount.
    # Whatever comes in each time (record_installment_payment) accumulates
    # here against tier.fee; Secretariat records amounts as they arrive,
    # same manual-confirmation pattern as every other payment in this
    # system. Activates on the FIRST payment (Association decision
    # 2026-08-07), balance carried as arrears until paid off.
    amount_paid = models.DecimalField(
        max_digits=10, decimal_places=2, default=0,
        help_text=_("Cumulative amount paid toward this row's tier fee. "
                    "For installment plans this is < tier.fee until paid off."),
    )
    next_installment_due = models.DateField(
        null=True, blank=True,
        help_text=_("When the next installment is expected, based on payment_frequency. "
                    "Only meaningful for installment plans (payment_frequency != Once)."),
    )

    # Issued items follow the membership, not the person.
    card_issued = models.BooleanField(default=False)
    certificate_issued = models.BooleanField(default=False)
    certificate_sent = models.BooleanField(default=False)
    certificate_generated_at = models.DateTimeField(null=True, blank=True)
    lapel_badge_issued = models.BooleanField(default=False)

    # Legacy paper-form artifact from the pre-digital membership register --
    # NOT DPA e-consent. Consent for SMS/email lives on UserProfile
    # (sms_opt_in/email_opt_in/consent_given_at) and is deliberately never
    # inferred from this field (docs/todo.md: legacy members start
    # unconsented, per the Association's own pending re-consent policy).
    legacy_signed = models.BooleanField(
        default=False,
        help_text=_("Physical signature on file from a paper membership form (legacy import only)."),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Membership")
        verbose_name_plural = _("Memberships")
        constraints = [
            models.UniqueConstraint(
                fields=["membership_number"],
                condition=models.Q(status="active"),
                name="unique_active_membership_number",
            ),
        ]

    def __str__(self):
        return f"{self.user.email} — {self.tier.name} ({self.get_status_display()})"

    @property
    def is_valid(self):
        """Single source of truth for membership validity."""
        if self.status != self.Status.ACTIVE:
            return False
        if self.is_lifetime:
            return True
        return bool(self.expires_on and self.expires_on >= timezone.now().date())

    def generate_membership_number(self):
        """UoNAA/001234/2025 -- unique per calendar year of activation."""
        year = timezone.now().year
        last = Membership.objects.filter(membership_number__endswith=f"/{year}").count()
        return f"UoNAA/{last + 1:06d}/{year}"

    def activate(self, payment_date=None):
        """Stamp dates/number off self.tier and mark active.

        Deliberately an instance method, not yet the module-level "one
        door" todo.md 1.3 asks for (renew_membership() /
        upgrade_to_lifetime() / assign_membership_tier(), callable from
        admin now and payment callbacks later without fragmenting state
        changes). That's real sequencing/business-rule work -- e.g.
        whether a renewal extends this row or opens a new one -- not a
        mechanical rename, so it isn't built here. This method is what
        that service layer will call.
        """
        payment_date = payment_date or timezone.now().date()
        self.status = self.Status.ACTIVE
        self.is_lifetime = self.tier.is_lifetime()
        self.started_on = self.started_on or payment_date
        self.expires_on = None if self.is_lifetime else self.tier.get_expiry_date(payment_date)
        if not self.membership_number:
            self.membership_number = self.generate_membership_number()
        self.save()

    @property
    def is_installment_plan(self):
        return self.payment_frequency != self.PaymentFrequency.ONCE

    @property
    def balance_due(self):
        """is_lifetime is about DURATION (never expires) -- orthogonal to
        whether the fee is fully paid. A Life Member paying in installments
        is lifetime AND has a balance due until amount_paid catches up
        with tier.fee; don't conflate the two."""
        if not self.tier_id:
            return Decimal("0")
        return max(self.tier.fee - self.amount_paid, Decimal("0"))

    @property
    def is_overdue(self):
        """Computed live, not dependent on the expire_lapsed_installment_plans
        management command having run -- so admin/dashboard display is
        always correct even between cron runs. The command is what
        actually flips status to EXPIRED for anything code elsewhere
        trusts status for (e.g. MembershipManager, is_valid)."""
        if not self.is_installment_plan or self.status != self.Status.ACTIVE:
            return False
        if self.balance_due <= 0 or not self.next_installment_due:
            return False
        grace_days = self.INSTALLMENT_FREQUENCY_DAYS.get(self.payment_frequency, 30)
        return timezone.now().date() > self.next_installment_due + timezone.timedelta(days=grace_days)

    def record_installment_payment(self, amount, payment_date=None):
        """The 'one door' for installment payments -- PaymentAdmin.mark_completed()
        calls this instead of activate() when a Payment is linked to a
        specific Membership row (Payment.membership). Activates on the
        FIRST call regardless of whether tier.fee is fully covered
        (Association decision 2026-08-07: active while paying, not only
        once paid off) -- subsequent calls just accumulate amount_paid
        and push next_installment_due forward.
        """
        payment_date = payment_date or timezone.now().date()
        self.amount_paid = (self.amount_paid or Decimal("0")) + amount

        if self.status != self.Status.ACTIVE:
            self.activate(payment_date=payment_date)
        else:
            self.save()

        if self.is_installment_plan and self.balance_due > 0:
            grace_days = self.INSTALLMENT_FREQUENCY_DAYS.get(self.payment_frequency, 30)
            self.next_installment_due = payment_date + timezone.timedelta(days=grace_days)
            self.save(update_fields=["next_installment_due"])


class Payment(models.Model):
    # Cash/Cheque removed 2026-08-07 (Association decision) -- everything
    # now routes through a traceable channel. M-Pesa's eligibility is
    # further gated per-tier (see MembershipTier.allows_mpesa below);
    # credit_card/bank_transfer stay available for every tier.
    PAYMENT_METHODS = [
        ('mpesa', 'M-Pesa'),
        ('credit_card', 'Credit/Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
    ]
    
    PAYMENT_STATUS = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
        ('pending_verification', 'Pending Verification'),
    ]
    
    # Relationships
    alumni = models.ForeignKey(
        'AlumniProfile',
        on_delete=models.CASCADE,
        related_name='payments'
    )
    membership_tier = models.ForeignKey(
        'MembershipTier',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments'
    )
    # Direct link to the specific Membership row this payment is an
    # installment toward (2026-08-07). Previously mark_completed() found
    # the row indirectly by matching (user, tier, status=pending), which
    # only works once -- a second installment against an already-active
    # membership would find nothing. Nullable/SET_NULL: older Payment rows
    # predate this field, and non-installment lump-sum payments still work
    # without it (mark_completed falls back to the old lookup when unset).
    membership = models.ForeignKey(
        'Membership',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='installment_payments',
    )

    # Payment details
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    
    # Transaction references
    transaction_reference = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    mpesa_receipt_number = models.CharField(max_length=50, blank=True, null=True)
    bank_reference = models.CharField(max_length=100, blank=True, null=True)
    
    # Payment details based on method
    mpesa_number = models.CharField(max_length=15, blank=True, null=True)
    card_last_four = models.CharField(max_length=4, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    
    # Timestamps
    payment_date = models.DateTimeField(default=timezone.now)
    completion_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Additional info
    notes = models.TextField(blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_payments'
    )
    
    class Meta:
        ordering = ['-payment_date']
        indexes = [
            models.Index(fields=['transaction_reference']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['payment_date']),
        ]
    
    def __str__(self):
        return f"{self.alumni.user.profile.full_name} - {self.amount} - {self.payment_status}"
    
    # ---------- Internal logging helper ----------
    def _log_transaction(self, trans_type, request_data=None, response_data=None, error_msg=None):
        """Create a PaymentTransaction record for audit trail."""
        PaymentTransaction.objects.create(
            payment=self,
            transaction_type=trans_type,
            request_data=request_data or {},
            response_data=response_data or {},
            error_message=error_msg or '',
            status_code=200 if not error_msg else 400
        )
    
    # ---------- Explicit status change methods (use these in code) ----------
    def mark_as_completed(self, receipt_number=None):
        """Mark payment as completed and optionally store receipt."""
        old_status = self.payment_status
        self.payment_status = 'completed'
        self.completion_date = timezone.now()
        
        if receipt_number:
            if self.payment_method == 'mpesa':
                self.mpesa_receipt_number = receipt_number
            elif self.payment_method == 'bank_transfer':
                self.bank_reference = receipt_number
        
        self.save(update_fields=['payment_status', 'completion_date', 'mpesa_receipt_number', 'bank_reference'])
        self._log_transaction('complete', request_data={'receipt': receipt_number})
    
    def mark_as_failed(self, reason=None):
        """Mark payment as failed with optional reason."""
        old_status = self.payment_status
        self.payment_status = 'failed'
        if reason:
            self.notes = reason
        self.save(update_fields=['payment_status', 'notes'])
        self._log_transaction('fail', error_msg=reason)
    
    def mark_as_pending_verification(self):
        """Use for bank transfers waiting admin approval."""
        self.payment_status = 'pending_verification'
        self.save(update_fields=['payment_status'])
        self._log_transaction('verify', request_data={'status': 'pending_verification'})
    
    def mark_as_refunded(self, reason=None):
        self.payment_status = 'refunded'
        if reason:
            self.notes = reason
        self.save(update_fields=['payment_status', 'notes'])
        self._log_transaction('refund', error_msg=reason)
    
    # ---------- Properties ----------
    @property
    def is_completed(self):
        return self.payment_status == 'completed'
    
    @property
    def is_pending(self):
        return self.payment_status in ['pending', 'pending_verification']



class PaymentTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('initiate', 'Initiated'),
        ('callback', 'Callback Received'),
        ('verify', 'Verification'),
        ('complete', 'Completed'),
        ('fail', 'Failed'),
        ('refund', 'Refunded'),
        ('status_change', 'Status Changed'),
    ]
    
    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    request_data = models.JSONField(null=True, blank=True)
    response_data = models.JSONField(null=True, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['payment', 'created_at']),
        ]
    
    def __str__(self):
        return f"{self.payment} - {self.transaction_type} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


