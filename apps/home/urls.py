from django.http import HttpResponse
from django.urls import path

app_name = 'home'


def index(request):
    return HttpResponse('Home app is installed.')


urlpatterns = [
    path('', index, name='index'),
]
