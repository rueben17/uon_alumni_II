from django.db import models
from django.utils.translation import gettext_lazy as _
from django_resized import ResizedImageField
from autoslug import AutoSlugField
from shortuuid.django_fields import ShortUUIDField
import uuid
from django.utils.text import slugify
from django.urls import reverse
from io import BytesIO
from PIL import Image
from django.utils.timezone import now
from django.utils import timezone
from django.core.validators import RegexValidator
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
import random
import string
from datetime import datetime
from django.core.files import File
from django.contrib.auth import get_user_model

User = get_user_model()
# Create your models here.


class Title(models.CharField):
    def __init__(self, *args, **kwargs):
        super(Title, self).__init__(*args, **kwargs)

    def get_prep_value(self, value):
        return str(value).title()


class Article(models.Model):

    ARTICLE_TYPE_CHOICES = [
        ('article', _('Article')),
        ('workshop', _('Workshop')),
        ('conference', _('Conference')),
        ('forum', _('Forum')),
        ('training', _('Training')),
    ]
    article_type = models.CharField(
        max_length=50,
        choices=ARTICLE_TYPE_CHOICES,
        default='article',
        verbose_name=_("Article Type")
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='articles')
    chapter = models.ForeignKey('Chapter', on_delete=models.CASCADE, related_name="articles",  blank=True, null=True)
    title =  Title(_("Title"), help_text=_("Required"), max_length=250)
    body = models.TextField()
    quote = models.TextField(max_length=1000,  blank=True, null=True)
    thumbnail = models.ImageField(upload_to='articles/images/', blank=True, null=True)
    article_banner_image = models.ImageField(upload_to='articles/banners/', blank=True, null=True)
    thumbnail_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(verbose_name=_("Created at"), default=timezone.now, blank=True)
    date_updated = models.DateTimeField(auto_now=True, verbose_name="date updated", blank=True)
    slug = AutoSlugField(populate_from='title',
                        unique_with=['created_at', ],
                        editable=True, always_update=True)
    is_feature = models.BooleanField(default=False)
    is_highlighted = models.BooleanField(default=False)


    def __str__(self):
        return f"{self.title}: {self.created_at}"


    class Meta:
        ordering = ['-created_at']
        unique_together = ('title', 'created_at')


    def get_absolute_url(self):
        return reverse("home:uon_alumni_article_detail", args=[self.slug])
    
    def get_thumbnail(self):
        if self.thumbnail:
            return self.thumbnail.url
        else:
            if self.thumbnail:
                self.thumbnail = self.make_thumbnail(self.thumbnail)
                self.save()

                return self.thumbnail.url
            else:
                return 'https://via.placeholder.com/240x240x.jpg'


    def make_thumbnail(self, image, size=(3648, 3648)):
        img = Image.open(image)
        img.convert('RGB')
        img.thumbnail(size)

        thumb_io = BytesIO()
        img.save(thumb_io, 'JPEG', quality=95)

        thumbnail = File(thumb_io, name=image.name)

        return thumbnail


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
    top_banner = ResizedImageField(size=[1400, 1400], quality=95, 
                        upload_to='banner/top_banner/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)
    middle_banner = ResizedImageField(size=[1400, 1400], quality=95, 
                        upload_to='banner/middle_banner/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)
    
    bottom_banner = ResizedImageField(size=[1400, 1400], quality=95, 
                        upload_to='banner/bottom_banner/%Y/%m/%d/',
                        help_text=_("Upload your item images "), blank=True, null=True)

    image = ResizedImageField(size=[1400, 1400], quality=95, 
                        upload_to='banner/image/%Y/%m/%d/',
                        help_text=_("Upload banner images "), blank=True, null=True)
    logo = ResizedImageField(size=[400, 400], quality=95, 
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
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="images",  blank=True, null=True)
    chapter = models.ForeignKey('Chapter', on_delete=models.CASCADE, related_name="images",  blank=True, null=True)
    event = models.ForeignKey('Event', on_delete=models.CASCADE, related_name="images",  blank=True, null=True)
    image = ResizedImageField(size=[1400, 1400], quality=95, 
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
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = _("Gallery Image")
        verbose_name_plural = _("Gallery Images")


    def __str__(self):
        try:
            return f"{self.article.title}: {self.alt_text[:30]}"
        except:
            return f"No Article Title : {self.created_at}"




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
    background_image = models.ImageField(
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




class Executive(models.Model):
    
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
    avatar = models.ImageField(upload_to='gallery/executive/', blank=True, null=True)


    class Meta:
        verbose_name = _("Executive")
        verbose_name_plural = _("Executive")


    def __str__(self):
        return f"{self.position}: {self.title}. {self.surname}"



    def get_avatar(self):
        if self.avatar:
            return self.avatar.url
        else:
            if self.avatar:
                self.avatar = self.make_avatar(self.avatar)
                self.save()
                return self.avatar.url
            else:
                return 'https://via.placeholder.com/240x240.jpg'


    def make_avatar(self, image, size=(3648, 3648)):
        img = Image.open(image)
        img.convert('RGB')
        img.thumbnail(size)

        thumb_io = BytesIO()
        img.save(thumb_io, 'JPEG', quality=95)

        avatar = File(thumb_io, name=image.name)

        return avatar



class Event(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title =  Title(_("Title"), help_text=_("Required"), max_length=250)
    body = models.TextField()
    thumbnail = ResizedImageField(size=[3648, 3648], quality=95, 
                        upload_to='walk/images/', 
                        blank=True, null=True)
    created_at = models.DateTimeField(verbose_name=_("Created at"), default=timezone.now, blank=True)
    date_updated = models.DateTimeField(auto_now=True, verbose_name="date updated", blank=True)
    slug = AutoSlugField(populate_from='title',
                        unique_with=['created_at', ],
                        editable=True, always_update=True)



    def __str__(self):
        return f"{self.title}: {self.created_at}"


    class Meta:
        ordering = ['-created_at']
        unique_together = ('title', 'created_at')


    def get_absolute_url(self):
        return reverse("home:uon_alumni_walk_detail", args=[self.slug])


    def get_thumbnail(self):
        if self.thumbnail:
            return self.thumbnail.url
        else:
            if self.thumbnail:
                self.thumbnail = self.make_thumbnail(self.thumbnail)
                self.save()

                return self.thumbnail.url
            else:
                return 'https://via.placeholder.com/240x240x.jpg'


    def make_thumbnail(self, image, size=(3648, 3648)):
        img = Image.open(image)
        img.convert('RGB')
        img.thumbnail(size)

        thumb_io = BytesIO()
        img.save(thumb_io, 'JPEG', quality=95)

        thumbnail = File(thumb_io, name=image.name)

        return thumbnail



class Faculty(models.Model):
    name = models.CharField(max_length=100)
    slug = AutoSlugField(populate_from='name',
                        editable=True, always_update=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _('Faculty')
        verbose_name_plural = _("Faculties")

    def __str__(self):
        return f"{self.name}"


    def get_absolute_url(self):
        return reverse("home:faculty",  args=[self.slug])



class Chapter(models.Model):
    faculty = models.ForeignKey(Faculty, related_name='chapters', on_delete=models.CASCADE, blank=True, null=True)
    name = models.CharField(max_length=100)
    about = models.TextField(blank=True, null=True)
    year_launched = models.DateTimeField(verbose_name=_("Launched On "),  blank=True, null=True)
    slug = AutoSlugField(populate_from='name',
                         unique_with=['year_launched', ],
                         editable=True, always_update=True, blank=True, null=True)
    thumbnail = ResizedImageField(size=[1080, 1080], quality=95, 
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
            faculty_slug = slugify(self.faculty.name)
            return reverse("home:uon_alumni_chapter_detail", args=[faculty_slug, self.slug])
        return reverse("home:uon_alumni_chapter_detail", args=[self.slug])



    def get_thumbnail(self):
        if self.thumbnail:
            return self.thumbnail.url
        else:
            if self.thumbnail:
                self.thumbnail = self.make_thumbnail(self.thumbnail)
                self.save()

                return self.thumbnail.url
            else:
                return 'https://via.placeholder.com/240x240x.jpg'



class Department(models.Model):
    faculty = models.ForeignKey(Faculty, related_name='departments', on_delete=models.CASCADE, blank=True, null=True)
    name = models.CharField(max_length=100)

    class Meta:
        verbose_name = _('Department')
        verbose_name_plural = _("Departments")

    def __str__(self):
        return f"{self.name}"




class Partner(models.Model):
    title =  Title(_("Title"), help_text=_("Required"), max_length=250)
    relation = models.CharField(
                    verbose_name=_("Partner Relation"),
                    help_text=_("Relation with UoNAA "),
                    max_length=125,
                    null=True,
                    blank=True,
                )
    thumbnail = ResizedImageField(size=[3648, 3648], quality=95, 
                        upload_to='gallery/partners/', 
                        blank=True, null=True)
    created_at = models.DateTimeField(verbose_name=_("Created at"), default=timezone.now, blank=True)
   
    def __str__(self):
        return f"{self.title}: {self.created_at}"


    class Meta:
        ordering = ['-created_at']
        unique_together = ('title', 'created_at')


    def get_thumbnail(self):
        if self.thumbnail:
            return self.thumbnail.url
        else:
            if self.thumbnail:
                self.thumbnail = self.make_thumbnail(self.thumbnail)
                self.save()

                return self.thumbnail.url
            else:
                return 'https://via.placeholder.com/240x240x.jpg'


    def make_thumbnail(self, image, size=(3648, 3648)):
        img = Image.open(image)
        img.convert('RGB')
        img.thumbnail(size)

        thumb_io = BytesIO()
        img.save(thumb_io, 'JPEG', quality=95)

        thumbnail = File(thumb_io, name=image.name)

        return thumbnail



class Secretariat(models.Model):

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

    title =  models.CharField(max_length=10, choices=TITLE, )
    first_name = models.CharField(_('First Name'), max_length=150, blank=True)
    middle_name = models.CharField(_('Middle Name'), max_length=150, blank=True)
    surname = models.CharField(_('Surname'), max_length=150, blank=True)
    position = models.CharField(_('Secretariat Position'), help_text=_("Secretariat Position"), max_length=255, choices=SECRETARIAT_POSITION, null=True, blank=True)
    rank = models.CharField(_('Secretariat Rank'), help_text=_("Secretariat Rank"), max_length=255, choices=RANK, null=True, blank=True)
    bio = models.TextField(_("Bio"), max_length=2500, blank=True, null=True)
    avatar = models.ImageField(upload_to='gallery/secretariat/', blank=True, null=True)


    class Meta:
        verbose_name = _("Secretariat")
        verbose_name_plural = _("Secretariat")


    def __str__(self):
        return f"{self.position}: {self.title}. {self.surname}"


    def get_avatar(self):
        if self.avatar:
            return self.avatar.url
        else:
            if self.avatar:
                self.avatar = self.make_avatar(self.avatar)
                self.save()
                return self.avatar.url
            else:
                return 'https://via.placeholder.com/240x240.jpg'


    def make_avatar(self, image, size=(3648, 3648)):
        img = Image.open(image)
        img.convert('RGB')
        img.thumbnail(size)

        thumb_io = BytesIO()
        img.save(thumb_io, 'JPEG', quality=95)

        avatar = File(thumb_io, name=image.name)

        return avatar



class MembershipTier(models.Model):
    TIER_TYPES = [
        ('life', 'Life Member'),
        ('annual', 'Annual Member'),
        ('honorary', 'Honorary Member'),
        ('corporate', 'Corporate Partner'),
    ]
    name = models.CharField(max_length=50)  # "Gold Life Member"
    fee = models.DecimalField(max_digits=10, decimal_places=2)
    tier_type = models.CharField(max_length=20, choices=TIER_TYPES)
    duration_months = models.IntegerField(default=0, help_text="0 = lifetime")
    is_active = models.BooleanField(default=True)
    order = models.IntegerField(default=0)  # for display order

    def __str__(self):
        return f"{self.name} - KES {self.fee}"
    
    def is_lifetime(self):
        """Check if this tier is a lifetime membership"""
        return self.tier_type == 'life' or self.duration_months == 0
    
    def get_expiry_date(self, start_date=None):
        """Calculate expiry date based on tier duration"""
        from django.utils import timezone
        from datetime import timedelta
        
        if start_date is None:
            start_date = timezone.now().date()
        
        if self.is_lifetime():
            return None  # Never expires
        
        return start_date + timedelta(days=self.duration_months * 30)   


class AlumniProfile(models.Model):
    TITLE_CHOICES = [
        ('Mr', 'Mr'), ('Mrs', 'Mrs'), ('Ms', 'Ms'),
        ('Dr', 'Dr'), ('Prof', 'Prof'), ('Rev', 'Rev'), ('Other', 'Other')
    ]
    GENDER_CHOICES = [('M', 'Male'), ('F', 'Female'), ('O', 'Other')]

    # Link to Django User (One-to-One)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='alumni_profile')

    # Personal details
    title = models.CharField(max_length=10, choices=TITLE_CHOICES)
    surname = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    maiden_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    date_of_birth = models.DateField()
    id_passport_no = models.CharField(max_length=50, unique=True)
    nationality = models.CharField(max_length=100, default='Kenyan')

    # Contact details
    postal_address = models.CharField(max_length=200, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    city = models.CharField(max_length=100, blank=True)
    phone_mobile = models.CharField(
        max_length=15,
        validators=[RegexValidator(r'^\+?254\d{9}$', message='Enter a valid Kenyan phone number (e.g., 2547XXXXXXXX)')]
    )
    phone_alt = models.CharField(max_length=15, blank=True)
    email = models.EmailField(unique=False, blank=True, null=True)

    # Alumni specific
    graduation_year = models.IntegerField(null=True, blank=True)
    faculty = models.ForeignKey(Faculty, on_delete=models.SET_NULL, null=True, blank=True)
    student_reg_no = models.CharField(max_length=50, blank=True)

    # Membership
    current_membership_tier = models.ForeignKey(MembershipTier, on_delete=models.SET_NULL, null=True, blank=True)
    membership_expiry = models.DateField(null=True, blank=True)
    is_lifetime_member = models.BooleanField(default=False)
    membership_number = models.CharField(max_length=20, unique=True, null=True, blank=True)

    # Issued items
    membership_card_issued = models.BooleanField(default=False)
    certificate_issued = models.BooleanField(default=False)
    certificate_sent = models.BooleanField(default=False)
    certificate_generated_at = models.DateTimeField(null=True, blank=True)
    lapel_badge_issued = models.BooleanField(default=False)

    # Preferences
    receive_newsletter = models.BooleanField(default=True)
    receive_sms_alerts = models.BooleanField(default=True)

    # Meta
    registration_date = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.title} {self.first_name} {self.surname}"

    @property
    def full_name(self):
        return f"{self.title} {self.first_name} {self.surname}"
        
    def generate_membership_number(self):
        """Generate a unique membership number, e.g., UoNAA/001234/2025"""
        from django.utils import timezone
        
        year = timezone.now().year
        # Count existing membership numbers for this year
        last = AlumniProfile.objects.filter(
            membership_number__endswith=f"/{year}"
        ).count()
        new_num = last + 1
        return f"UoNAA/{new_num:06d}/{year}"

    @property
    def is_membership_valid(self):
        """Check if current membership is valid"""
        if self.is_lifetime_member:
            return True
        if self.membership_expiry:
            return self.membership_expiry >= timezone.now().date()
        return False

    def assign_membership_tier(self, tier, payment_date=None):
        """Assign a membership tier to the alumni"""
        from django.utils import timezone
        
        if payment_date is None:
            payment_date = timezone.now().date()
        
        self.current_membership_tier = tier
        
        # Use the is_lifetime method from MembershipTier
        self.is_lifetime_member = tier.is_lifetime()
        
        # Set expiry date if not lifetime
        if not self.is_lifetime_member:
            self.membership_expiry = tier.get_expiry_date(payment_date)
        else:
            self.membership_expiry = None
        
        # Generate membership number if not exists
        if not self.membership_number:
            self.membership_number = self.generate_membership_number()  # Now this works as a method call
        
        self.save()

    def renew_membership(self, tier, payment_date=None):
        """Renew or upgrade membership"""
        from django.utils import timezone
        from datetime import timedelta
        
        if payment_date is None:
            payment_date = timezone.now().date()
        
        # If renewing same tier, extend expiry
        if self.current_membership_tier == tier and not tier.is_lifetime():
            if self.membership_expiry and self.membership_expiry > payment_date:
                # Extend from current expiry
                self.membership_expiry = self.membership_expiry + timedelta(days=tier.duration_months * 30)
            else:
                # Start from payment date
                self.membership_expiry = tier.get_expiry_date(payment_date)
        else:
            # New tier assignment
            self.assign_membership_tier(tier, payment_date)
        
        self.save()

    def upgrade_to_lifetime(self, lifetime_tier):
        """Upgrade to lifetime membership"""
        if not lifetime_tier.is_lifetime():
            raise ValueError("Selected tier is not a lifetime membership")
        
        self.current_membership_tier = lifetime_tier
        self.is_lifetime_member = True
        self.membership_expiry = None
        self.save()



        
class Payment(models.Model):
    PAYMENT_METHODS = [
        ('mpesa', 'M-Pesa'),
        ('credit_card', 'Credit/Debit Card'),
        ('bank_transfer', 'Bank Transfer'),
        ('cash', 'Cash'),
        ('cheque', 'Cheque'),
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
        return f"{self.alumni.full_name} - {self.amount} - {self.payment_status}"
    
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