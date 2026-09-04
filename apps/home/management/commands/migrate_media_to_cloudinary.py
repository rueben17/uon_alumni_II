"""Move media already on the local filesystem into the configured storage.

Background: STATICFILES_STORAGE/DEFAULT_FILE_STORAGE were removed in
Django 5.1 and ignored in 5.2, so Cloudinary was configured but never
used and every upload landed on the VPS disk (finding L). Once
main/settings.py defines STORAGES, NEW uploads go to Cloudinary --
this moves the existing ones and repoints their database fields.

Deliberately a management command rather than Cloudinary's own upload
tooling: the bytes are the easy half. The database rows have to be
repointed too, and only Django knows which row holds which name.

Safety properties, in order of importance:

  * It NEVER deletes the local copy. Removing the local tree is a
    separate, explicitly-approved step once the remote copies are
    verified.
  * It is idempotent. A row whose file already exists in the target
    storage is skipped, so a half-finished or interrupted run resumes
    correctly. That check is a real confirmation, not bookkeeping.
  * It reads from MEDIA_ROOT explicitly, NOT through field.open(). Once
    STORAGES points at Cloudinary the field's own storage looks there,
    where the file does not exist yet -- reading through it would report
    every file as missing.
  * A row whose file is already gone from disk is logged and skipped
    rather than raising, so one orphaned row cannot halt the run.

--dry-run is the safe default posture: it reports what would move and
writes nothing, locally or remotely.
"""
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import FileField
from django.core.management.base import BaseCommand, CommandError

# Already pinned to RawMediaCloudinaryStorage on the model, so it has been
# writing to Cloudinary all along, independent of the broken default.
# Nothing to move, and re-saving it would be a pointless round trip.
EXCLUDED_FIELDS = {("home", "Publication", "file")}


class Command(BaseCommand):
    help = "Copy locally-stored media into the configured default storage and repoint the fields."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would move without writing anything.",
        )
        parser.add_argument(
            "--model", dest="model_label", default=None,
            help="Limit to one model, as app_label.ModelName (e.g. home.Banner).",
        )

    # ---------------------------------------------------------------

    def _fields_to_migrate(self, model_label):
        """Every FileField/ImageField in the project, minus the exclusions."""
        if model_label:
            try:
                app_label, model_name = model_label.split(".")
                models = [apps.get_model(app_label, model_name)]
            except (ValueError, LookupError) as exc:
                raise CommandError(f"Unknown --model {model_label!r}: {exc}")
        else:
            models = apps.get_models()

        for model in models:
            label = model._meta.app_label
            for field in model._meta.get_fields():
                if not isinstance(field, FileField):
                    continue
                if (label, model.__name__, field.name) in EXCLUDED_FIELDS:
                    continue
                yield model, field

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        media_root = Path(settings.MEDIA_ROOT)

        self.stdout.write(
            f"Target storage: {default_storage.__class__.__name__}"
        )
        self.stdout.write(f"Reading local files from: {media_root}")
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN -- nothing will be written."))

        moved = skipped_present = skipped_missing = errors = 0

        for model, field in self._fields_to_migrate(options["model_label"]):
            queryset = model._default_manager.exclude(
                **{field.name: ""}
            ).exclude(**{f"{field.name}__isnull": True})

            for instance in queryset.iterator():
                file_field = getattr(instance, field.name)
                name = file_field.name
                if not name:
                    continue

                # Already in the target storage -- the idempotency check.
                if default_storage.exists(name):
                    skipped_present += 1
                    continue

                local_path = media_root / name
                if not local_path.exists():
                    skipped_missing += 1
                    self.stdout.write(self.style.WARNING(
                        f"  missing on disk: {model.__name__}.{field.name} "
                        f"#{instance.pk} -> {name}"
                    ))
                    continue

                if dry_run:
                    moved += 1
                    self.stdout.write(
                        f"  would move: {model.__name__}.{field.name} #{instance.pk} -> {name}"
                    )
                    continue

                # default_storage.save(), NOT file_field.save() (2026-09-04,
                # caught by a real run before it reached production):
                # FieldFile.save() always re-derives the name through the
                # field's generate_filename()/upload_to, which reapplies a
                # %Y/%m/%d-style pattern using TODAY's date -- it does NOT
                # preserve the original `name` passed in. A live attempt
                # relanded Banner.top_banner under 2026/09/04 instead of its
                # real 2026/08/19 path, with a Cloudinary-appended random
                # suffix on top, defeating the entire point of this command.
                # It also runs the field's own save-time side effects (e.g.
                # Banner.top_banner's ResizedImageField re-resizing an image
                # that was already sized correctly on its original upload) --
                # unwanted for a pure "move the bytes, repoint the row"
                # operation. default_storage.save(name, content) has neither
                # problem: Storage.save() only renames on an actual naming
                # collision (already ruled out by the exists() check above),
                # and it skips every field-specific save-time hook entirely.
                #
                # Wrapped per-instance in its own transaction, and the whole
                # write in a try/except: one bad row (the trigger for this
                # fix was a DataError on the very next field) must be logged
                # and skipped, not crash the entire run partway through --
                # same reasoning as apps/home/management/commands/
                # import_legacy_memberships.py's per-row isolation.
                try:
                    with transaction.atomic():
                        with local_path.open("rb") as handle:
                            saved_name = default_storage.save(name, File(handle))
                        setattr(instance, field.name, saved_name)
                        instance.save(update_fields=[field.name])
                except Exception as exc:  # noqa: BLE001 -- one bad row must not abort the batch
                    errors += 1
                    self.stdout.write(self.style.ERROR(
                        f"  error: {model.__name__}.{field.name} #{instance.pk} -> {name}: {exc}"
                    ))
                    continue

                moved += 1
                self.stdout.write(
                    f"  moved: {model.__name__}.{field.name} #{instance.pk} -> {saved_name}"
                )

        verb = "would move" if dry_run else "moved"
        self.stdout.write(self.style.SUCCESS(
            f"Done: {moved} file(s) {verb}, {skipped_present} already present, "
            f"{skipped_missing} missing on disk, {errors} error(s). "
            "No local file was deleted."
        ))
