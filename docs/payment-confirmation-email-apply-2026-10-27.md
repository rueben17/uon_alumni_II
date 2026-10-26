# Payment-confirmation email: acknowledgement letter + invoice — 2026-10-27

## What this is
Once a member's `Payment` is confirmed (`Payment.mark_as_completed()`,
reached from the Secretariat CRM's `RecordPaymentView`/`ConfirmPaymentView`,
`PaymentAdmin`'s bulk action/change-form save, or `AlumniRegisterView`'s
initial registration flow), the member now automatically receives an
email with two PDF attachments: an acknowledgement letter and an invoice.

Built because two reference PDFs from the Association's prior system
(`docs/Acknowledgement_Dan_UONAA_...pdf`, `docs/Invoice_Dan_UONAA_...pdf`)
were dropped in for this purpose, and the related view
(`apps/home/views.py`'s `download_payment_receipt`) had been an explicit
501 stub since 2026-08-10, left deliberately pending exactly this
decision.

## What was built
- **`apps/home/pdf_documents.py`** (new) — `build_acknowledgement_letter_pdf(payment)`
  and `build_invoice_pdf(payment)`, using reportlab platypus (same
  `SimpleDocTemplate` + flowables pattern as the existing QR membership
  card). A clean equivalent of the old documents' layout, not a pixel
  replica — no vendor-specific barcode/"digital signature" hash and no
  diagonal PAID ribbon graphic. The invoice's barcode is replaced with a
  QR code (plain informational payload, not a verification link).
- **`EmailLog.EmailType.PAYMENT_CONFIRMATION`** (`apps/home/models.py`) —
  new choice, migration `0046_alter_emaillog_email_type`.
- **`apps/home/tasks.py`'s `send_payment_confirmation_documents(payment_id)`** —
  new Django Q2 task, same idempotency pattern as the other `EmailLog`-backed
  tasks. First task in the codebase to send an email with attachments
  (`django.core.mail.EmailMessage` + `.attach()`, rather than `send_mail`).
- **Hook**: `Payment.mark_as_completed()` enqueues the task via
  `transaction.on_commit(...)` right after `services.confirm_payment(self)`
  succeeds — the one door every confirmation path already funnels through,
  so no per-call-site wiring was needed.
- **Settings constants** (`main/settings.py`): `UONAA_MPESA_PAYBILL`,
  `UONAA_BANK_NAME`, `UONAA_BANK_ACCOUNT_NUMBER`, `UONAA_BANK_SWIFT_CODE`,
  `UONAA_SIGNATORY_NAME`, `UONAA_SIGNATORY_TITLE` — confirmed current by
  the Association before hardcoding.
- **Tests** (`apps/home/tests.py`): enqueue-on-completion (and
  not-re-enqueued-on-a-second-call), both PDF builders produce valid PDF
  bytes for an annual and a lifetime tier, and the task's happy path +
  idempotency via `django.core.mail.outbox`/`EmailLog`.

## A real bug this surfaced
`payment.membership` is **not** reliably set — it's only ever populated
for installment-linked payments. For the common lump-sum case (including
every CRM-recorded payment and most registrations), `services.confirm_payment()`
creates/activates a `Membership` but never writes it back onto the
`Payment` row. Both builders resolve the member's actual membership via
`Membership.objects.current_active_for(user)` instead (the same lookup
`AlumniProfileDetailView`/`download_alumni_qr_code` already use) — see
`pdf_documents._resolve_membership()`.

## Deliberately deferred (not blocking, follow-ups)
- **Real SMTP delivery.** `EMAIL_BACKEND` is still the console backend
  unconditionally (`main/settings.py`) — no real email (including the
  pre-existing registration-confirmation email) is actually delivered
  today, anywhere. Wiring real SMTP (a Gmail App Password or Google
  Workspace SMTP relay) is a `.env`-only change, no code change needed.
- **Real signature/stamp images.** Neither exists in this repo. The
  letter builder reads them from `static/images/signatures/executive_director.png`
  and `static/images/stamps/uonaa_seal.png` and silently omits whichever
  is missing — drop the real PNGs in at those exact paths later and
  they'll appear with no code change.
- **`download_payment_receipt` is still a 501 stub.** Both PDF builders
  are already reusable to un-stub it (same `io.BytesIO()` + return-bytes
  shape) — not done in this pass, out of scope.
