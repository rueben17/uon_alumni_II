# Branded HTML emails — 2026-10-27

## What this is
Every member-facing outgoing email was plain text (`send_mail`, an
inline f-string body) — this is the first use of `render_to_string`
and `EmailMultiAlternatives` in this codebase. Built from a reference
screenshot of the Association's Gmail signature
(`media/google_auth/SMTP.png`): address/phone, a clickable
"University of Nairobi Alumni Association | Email" line, social links
(Facebook/LinkedIn/Twitter/WhatsApp), a dashed divider, and a logo row.

## What was built
- **`apps/home/branding.py`** (new) — `site_base_url()`,
  `static_image_url()` (percent-encodes the path — the crest file's own
  name has a literal space, `UoN CREST_new-01.png`, which must be
  encoded for a reliable `<img src>` in strict email clients), and
  `email_branding_context()`, the shared context every branded email
  template renders with.
- **`templates/emails/`** (new directory) — `base_email.html` (table
  layout, all CSS inline — email clients don't load stylesheets or run
  JS, so this is a parallel design to `templates/snippets/footer.html`,
  not a reuse of it) plus four templates extending it:
  `registration_confirmation.html`, `payment_confirmation.html`,
  `newsletter_announcement.html`, `otp_code.html`.
- **`apps/home/tasks.py`** — all four corresponding send functions now
  build an `EmailMultiAlternatives` (text/plain body unchanged from
  before, HTML attached via `.attach_alternative()`) instead of
  `send_mail`. `send_payment_confirmation_documents`'s two PDF
  attachments are untouched — `EmailMultiAlternatives` subclasses
  `EmailMessage`, so `.attach()` and `.attach_alternative()` both work
  on the same message.
- **`main/settings.py`** — new `UONAA_WEBSITE_URL`/`UONAA_CONTACT_EMAIL`/
  `UONAA_FACEBOOK_URL`/`UONAA_LINKEDIN_URL`/`UONAA_TWITTER_URL`/
  `UONAA_WHATSAPP_URL` constants (public info, not secrets — same
  plain-constants precedent as the bank/paybill details added earlier).
- **`apps/home/context_processors.py`'s `contacts()`** — now also
  passes `url_facebook`/`url_linkedin`/`url_twitter` into every page's
  context.
- **`templates/snippets/footer.html`** — its three matching social
  icons (`href=""` since the footer was first built) now use those real
  URLs. Instagram's icon is untouched (no URL provided, out of scope).
- **Tests** (`apps/home/tests.py`) — new coverage for all four tasks'
  HTML alternative (asserts `mail.outbox[0].alternatives` carries the
  right dynamic content), plus `EmailBrandingContextTests` proving the
  badge row is omitted cleanly when the files don't exist.

## Scope decision
Two other `send_mail` sites were found during research —
`apps/home/views.py`'s `_notify_contact_message` (internal, best-effort
notification to the Association's own inbox) and
`apps/student/tasks.py`'s `send_evaluation_receipt` (internal
confirmation to a staff interviewer). Neither is a member-facing
"campaign" email, so neither was touched here. Both are a straightforward
follow-up with the same `base_email.html` if wanted later.

## Badge images
The user supplied the combined reference image
(`media/google_auth/email.jpg`, a single 1800x556 JPG with all three
logos side by side). Split into three trimmed PNGs via a one-off PIL
script (whitespace-gutter detection + bounding-box auto-trim, not a
naive equal-thirds split -- the 20th-anniversary badge's subtitle text
is wider than its "20" graphic and would've been cut off) and committed
to `static/images/badges/`: `50th_anniversary.png`, `uonaa_crest.png`
(the Association's own circular seal -- used in the signature's badge
row specifically; does **not** replace `UoN CREST_new-01.png`, which
stays as the header logo), `20th_anniversary.png`. The
graceful-omission mechanism in `email_branding_context()` stays in
place regardless (now proven working both ways: present → included,
absent → omitted, both covered by tests), so a future re-crop/replacement
still needs no code change.

## Deliberately deferred
- **Real SMTP** is already wired up (earlier this session) — these
  HTML emails will actually deliver once this batch is deployed, same
  as the plain-text ones did before.
