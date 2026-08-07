# apps/home/management/commands/seed_legal_pages.py
"""
Seeds the Privacy Policy and Cookie Policy standing pages.

Content is a compliance-oriented DRAFT against Kenya's Data Protection Act
2019 -- covers what's collected, why, retention, the QR scan-log purpose
specifically (docs/todo.md's 1.1 blocker requires this), and DPA data
subject rights. It is NOT lawyer-reviewed; the Association should have it
checked before treating it as final. Re-running this command is safe --
it updates the existing rows in place (matched by page_key) rather than
duplicating them, so edits made here just need a re-run to take effect.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.home.models import Article
from apps.user.models import CURRENT_PRIVACY_NOTICE_VERSION

PRIVACY_VERSION = CURRENT_PRIVACY_NOTICE_VERSION
PRIVACY_BODY = f"""Version {PRIVACY_VERSION} -- effective {timezone.now():%d %B %Y}

The University of Nairobi Alumni Association (UoNAA, "we", "us") is committed to protecting your personal data in line with Kenya's Data Protection Act, 2019 ("the DPA"). This notice explains what we collect, why, and what rights you have over it.

1. WHO WE ARE
UoNAA is the data controller for the personal data described in this notice. For any data protection query, contact the Secretariat through the details on our Contact page.

2. WHAT WE COLLECT
- Identity data: honorific, full name, date of birth, national ID/passport number, gender, nationality.
- Contact data: phone number(s), email address(es), postal and physical address.
- Academic data: faculty, qualification, graduation year, and (where applicable) student registration number.
- Employment data: current employer and position, where you choose to provide it.
- Membership data: tier, subscription amount, status, membership number, and renewal/upgrade history.
- Photographs, where you upload a profile photo.
- For staff members using the QR badge system: scan events (when and where a badge was scanned), kept only long enough to serve the purpose below, then deleted.

3. WHY WE COLLECT IT
- To register and administer your membership, including verifying eligibility and processing subscriptions.
- To communicate with you: renewal reminders, event notices, newsletters -- only where you have opted in.
- To maintain the alumni directory, where you have chosen to make your details visible to other members.
- To issue and verify membership credentials (physical card, digital QR page) and, for staff, identity badges.
- QR scan logs exist solely to detect misuse of a badge (e.g. a lost or cloned credential) and are not used for movement tracking or performance monitoring. They are retained for a limited period (see Section 5) and then permanently deleted.

4. LEGAL BASIS
We process your data on the basis of your consent (for optional communications and directory visibility), the performance of your membership with the Association, and our legitimate interest in administering that membership and keeping our records accurate.

5. RETENTION
We keep membership and academic records for as long as you remain a member and for a reasonable period afterward for historical and reporting purposes. QR scan logs are retained for a limited operational window and then deleted; they are the one category of data in this system with a firm, short retention limit, precisely because they are the most sensitive to keep longer than necessary.

6. WHO WE SHARE IT WITH
We use third-party service providers to operate this site: cloud hosting and database infrastructure, image/file storage (Cloudinary), and Google for sign-in. These providers process data on our behalf under their own security commitments and may store data outside Kenya. We do not sell your data.

7. YOUR RIGHTS UNDER THE DPA
You have the right to: be informed how your data is used (this notice); access the data we hold about you; request correction of inaccurate data; request deletion of your data, subject to our legitimate retention needs; object to or restrict certain processing; and withdraw consent at any time for anything that depends on it (e.g. newsletters, SMS alerts, directory visibility). To exercise any of these rights, contact the Secretariat.

8. CHANGES TO THIS NOTICE
If we materially change how we handle your data, we will update the version number above and, where required, ask for fresh consent.

This notice is a working draft prepared alongside the system that enforces it, pending formal review by the Association's leadership."""

COOKIES_VERSION = "1.0"
COOKIES_BODY = f"""Version {COOKIES_VERSION} -- effective {timezone.now():%d %B %Y}

This page explains the cookies this site uses. It works alongside our Privacy Policy, which explains how we handle your personal data more broadly.

1. WHAT ARE COOKIES
Cookies are small files stored in your browser that let a site remember information between visits or between pages of the same visit.

2. COOKIES WE USE
- Session cookie: keeps you signed in as you move between pages. Without it, you would need to sign in again on every page. Strictly necessary -- cannot be switched off if you want to use member features.
- CSRF protection cookie: a security measure that stops other sites from submitting forms on this site on your behalf. Strictly necessary.
- Sign-in cookie (Google): if you sign in with Google, Google sets its own cookies as part of that process, governed by Google's own privacy policy, not ours.
- Cookie notice preference: remembers that you have seen and dismissed the cookie notice on this site, so it does not show again on your next visit.

3. WHAT WE DO NOT USE
We do not use third-party advertising or cross-site tracking cookies.

4. MANAGING COOKIES
Most browsers let you view, delete, and block cookies through their settings. Blocking the strictly necessary cookies above will prevent you from signing in or using member features of this site.

This notice is a working draft prepared alongside the system that enforces it, pending formal review by the Association's leadership."""


class Command(BaseCommand):
    help = "Seed/update the Privacy Policy and Cookie Policy standing pages"

    def handle(self, *args, **options):
        pages = [
            {
                "page_key": Article.PageKey.PRIVACY,
                "title": "Privacy Policy",
                "body": PRIVACY_BODY,
            },
            {
                "page_key": Article.PageKey.COOKIES,
                "title": "Cookie Policy",
                "body": COOKIES_BODY,
            },
        ]

        for page in pages:
            article, created = Article.objects.update_or_create(
                page_key=page["page_key"],
                defaults={
                    "type": Article.ArticleType.PAGE,
                    "title": page["title"],
                    "body": page["body"],
                    "is_published": True,
                },
            )
            verb = "Created" if created else "Updated"
            self.stdout.write(f"  {verb} standing page: {article.title} ({page['page_key']})")

        self.stdout.write(self.style.SUCCESS("Done."))
