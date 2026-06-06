from django.http import HttpResponse
from django.urls import path

app_name = 'home'


def index(request):
    return HttpResponse('Welcome to the new University of Nairobi Alumni Verification Portal.')


urlpatterns = [
    path('', index, name='index'),
]
