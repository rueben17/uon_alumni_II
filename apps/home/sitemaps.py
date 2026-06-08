# sitemaps.py
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class UonAlumniStaticSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.8

    def items(self):
        return [
            'home:uon_alumni_home',
            'home:uon_alumni_register',
            'home:uon_alumni_chapters',
            'home:uon_alumni_donate',
            'home:uon_alumni_all_news',
            'home:uon_alumni_contact_us',
        ]

    def location(self, item):
        return reverse(item)