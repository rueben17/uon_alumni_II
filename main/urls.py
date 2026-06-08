"""
URL configuration for main project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from apps.home.sitemaps import UonAlumniStaticSitemap 


sitemaps = {'static': UonAlumniStaticSitemap}

urlpatterns = [
    # path("", TemplateView.as_view(template_name="home/alumni_home.html"), name="home"),
    path("", include('apps.home.urls', namespace="home")), 
    path("2005/", admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap'),
    
    # path('user/', include('apps.user.urls', namespace="user")), 
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [
        # path("admin/", admin.site.urls),
        # path('admin/', include('admin_honeypot.urls', namespace='admin_honeypot')),
        # path('__debug__/', include(debug_toolbar.urls)),
    ]