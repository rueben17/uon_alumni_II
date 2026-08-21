# sitemaps.py
from django.conf import settings
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from apps.home.models import Article, Chapter, Event


class UonAlumniSitemap(Sitemap):
    """Base class every sitemap here extends.

    Sitemap.get_domain() ignores a self.domain attribute entirely once a
    Site is available (django.contrib.sites IS installed, and
    django.contrib.sitemaps.views.sitemap always passes one via
    get_current_site(request)) -- confirmed by reading Django's own
    get_domain() source, not assumed. That Site row (id=1) is still
    Django's untouched default, 'example.com' (confirmed directly against
    the production database, 2026-08-18) -- so without this override,
    every sitemap URL on this site would read
    "https://example.com/...". get_domain() is overridden outright, not
    just a domain attribute set, since only overriding the method actually
    takes effect.

    Same DEBUG-conditional domain construction as SUBDOMAIN_DOMAIN/
    QR_SCAN_ORIGIN (main/settings.py) -- deliberately not a new pattern.

    'www.' + SUBDOMAIN_DOMAIN in production, not settings.SUBDOMAIN_DOMAIN
    bare (2026-08-19, SEO Search Console readiness audit,
    docs/seo-search-console-readiness-2026-08-19.md finding 2.2): the
    production web server 301s the bare domain to www. on every path
    (confirmed live via curl, not read from this repo -- that redirect
    lives in nginx config, not here), so every one of this sitemap's URLs
    was a 301, not a final destination. lvh.me in DEBUG is untouched --
    local dev has no such redirect (main/settings.py's SUBDOMAIN_URLCONFS
    maps both None and 'www' to main.urls directly), so there's nothing to
    correct there.
    """
    protocol = 'http' if settings.DEBUG else 'https'

    def get_domain(self, site=None):
        return 'lvh.me:8000' if settings.DEBUG else f'www.{settings.SUBDOMAIN_DOMAIN}'


class UonAlumniStaticSitemap(UonAlumniSitemap):
    """Every plain, unparameterized public page on the main subdomain that
    doesn't require login. 'uon_alumni_register' was on this list before
    the 2026-08-18 SEO audit -- removed: it's LoginRequiredMixin-gated
    (apps/home/views.py's AlumniRegisterView), so a crawler can never
    actually reach it, and the audit's own rule is that any authenticated
    page is noindex. 'alumni_detail' (individual alumni profiles) is
    deliberately never listed here either -- same reasoning as the
    QR-badge noindex rule: a member's name/tier/county shouldn't be
    permanently searchable (decided with the user, 2026-08-18)."""
    changefreq = 'monthly'
    priority = 0.8

    def items(self):
        return [
            'home:uon_alumni_home',
            'home:uon_alumni_history',
            'home:uon_alumni_exec_committee',
            'home:uon_alumni_gallery',
            'home:membership_categories',
            'home:uon_alumni_donate',
            'home:uon_alumni_scholarship',
            'home:uon_alumni_in_memoriam',
            'home:uon_alumni_contact_us',
            'home:uon_alumni_article_list',
            'home:uon_alumni_walk_list',
            'home:uon_alumni_chapter_list',
            'home:uon_alumni_secretariat',
            'home:uon_alumni_partners',
            'home:uon_alumni_mission_vision',
            'home:uon_alumni_downloads',
            'home:uon_alumni_careers',
        ]

    def location(self, item):
        return reverse(item)


class StandingPageSitemap(UonAlumniSitemap):
    """The generic page/<page_key>/ route (apps/home/views.py's
    standing_page) -- covers every Article.PageKey NOT already served by
    its own dedicated view above (history/donate/scholarship/contact-us
    have their own routes; this is the rest: categories-benefits,
    digital-id, corporates, notable-alumni, agm, consultancy-training,
    terms, privacy, cookies, shop)."""
    changefreq = 'monthly'
    priority = 0.6

    _DEDICATED_PAGE_KEYS = {
        Article.PageKey.HISTORY, Article.PageKey.DONATE,
        Article.PageKey.SCHOLARSHIP, Article.PageKey.CONTACT,
    }

    def items(self):
        return (
            Article.objects.filter(type=Article.ArticleType.PAGE, is_published=True)
            .exclude(page_key__in=self._DEDICATED_PAGE_KEYS)
            .exclude(page_key__isnull=True)
        )

    def location(self, item):
        return reverse('home:standing_page', args=[item.page_key])

    def lastmod(self, item):
        return item.date_updated


class ArticleSitemap(UonAlumniSitemap):
    """News/features/notices -- same is_published + exclude(type=PAGE)
    filter ArticleListView/ArticleDetailView already use
    (apps/home/views.py), so this can never list a draft or a standing
    page under the news URL."""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return (
            Article.objects.filter(is_published=True)
            .exclude(type=Article.ArticleType.PAGE)
            .order_by('-created_at')
        )

    def lastmod(self, item):
        return item.date_updated


class EventSitemap(UonAlumniSitemap):
    """The 'UoN Alumni Walk' listing -- scoped to event_type=WALK, same as
    EventListView/EventDetailView. Workshop/conference/forum/training
    exist on the model but nothing routes to them yet (see EventListView's
    own docstring), so there's no URL to put in a sitemap for those."""
    changefreq = 'weekly'
    priority = 0.6

    def items(self):
        return Event.objects.filter(event_type=Event.EventType.WALK).order_by('-created_at')

    def lastmod(self, item):
        return item.date_updated


class ChapterSitemap(UonAlumniSitemap):
    """No is_published/is_active field on Chapter -- ChapterListView
    itself lists every row unfiltered, so this matches that."""
    changefreq = 'monthly'
    priority = 0.5

    def items(self):
        return Chapter.objects.select_related('faculty').order_by('name')
