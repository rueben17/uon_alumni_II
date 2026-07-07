from django.conf import settings


class SubdomainRoutingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.META.get('HTTP_HOST', '').lower()
        if ':' in host:
            host = host.split(':')[0]

        base = settings.SUBDOMAIN_DOMAIN

        if host == base:
            subdomain = None                      # apex: uonalumni.or.ke / lvh.me
        elif host.endswith(f'.{base}'):
            subdomain = host[:-(len(base) + 1)]   # 'staff', 'students', 'www'
        else:
            subdomain = None                      # IPs, localhost, unknown hosts

        request.subdomain = subdomain

        # Keep allauth on the shared ROOT_URLCONF on every subdomain —
        # this is the common /accounts/ login path.
        if not request.path.startswith('/accounts/'):
            urlconf_map = getattr(settings, 'SUBDOMAIN_URLCONFS', {})
            request.urlconf = urlconf_map.get(subdomain, settings.ROOT_URLCONF)

        return self.get_response(request)