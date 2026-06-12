from django.conf import settings


class SubdomainRoutingMiddleware:

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.META.get('HTTP_HOST', '').lower()
        if ':' in host:
            host = host.split(':')[0]

        parts = host.split('.')
        subdomain = parts[0] if len(parts) > 2 else None
        request.subdomain = subdomain

        urlconf_map = getattr(settings, 'SUBDOMAIN_URLCONFS', {})
        request.urlconf = urlconf_map.get(subdomain, settings.ROOT_URLCONF)

        return self.get_response(request)