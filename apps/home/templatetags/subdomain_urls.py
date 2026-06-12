from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def subdomain_url(context, view_name, subdomain):
    request = context['request']
    protocol = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    port = ':' + host.split(':')[1] if ':' in host else ''
    base = settings.SUBDOMAIN_DOMAIN
    urlconf = settings.SUBDOMAIN_URLCONFS.get(subdomain)

    # Strip the namespace prefix before reversing against the urlconf directly.
    # e.g. 'staff:all_uon_staff' → 'all_uon_staff'
    if urlconf and ':' in view_name:
        view_name = view_name.split(':', 1)[1]

    path = reverse(view_name, urlconf=urlconf) if urlconf else '/'
    return f"{protocol}://{subdomain}.{base}{port}{path}"