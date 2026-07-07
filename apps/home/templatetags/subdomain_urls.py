from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def subdomain_url(context, view_name, subdomain=None, *args, **kwargs):
    """
    Build a full cross-subdomain URL, e.g.:
      {% subdomain_url 'staff:all_uon_staff' 'staff' %}
        → http://staff.lvh.me:8000/
      {% subdomain_url 'home:index' %}
        → http://lvh.me:8000/

    View names are passed to reverse() exactly as written — use the
    namespaced form ('staff:...') everywhere.
    """
    request = context['request']
    scheme = 'https' if request.is_secure() else 'http'
    host = request.get_host()
    port = ':' + host.split(':')[1] if ':' in host else ''
    base = settings.SUBDOMAIN_DOMAIN

    urlconf = settings.SUBDOMAIN_URLCONFS.get(subdomain, settings.ROOT_URLCONF)
    path = reverse(view_name, urlconf=urlconf, args=args, kwargs=kwargs)

    host_part = f'{subdomain}.{base}' if subdomain else base
    return f'{scheme}://{host_part}{port}{path}'