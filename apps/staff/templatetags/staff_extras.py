from django import template

register = template.Library()


@register.filter
def cloudinary_download(url):
    """
    Turn a Cloudinary delivery URL into a force-download URL by
    inserting the fl_attachment transformation:
      .../image/upload/v123/x.png → .../image/upload/fl_attachment/v123/x.png
    Non-Cloudinary URLs (local dev MEDIA) pass through unchanged.
    """
    marker = "/upload/"
    if marker in url:
        return url.replace(marker, "/upload/fl_attachment/", 1)
    return url