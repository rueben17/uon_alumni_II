from django.shortcuts import render

from apps.home.models import*

# Create your views here.







def uon_alumni_home(request):
    
    context = {

    }
    return render(request, "home/alumni_home.html", context)



def uon_alumni_history(request):
    return render(request, 'home/uon_alumni_history.html')


def uon_alumni_gallery(request):
    return render(request, 'home/uon_alumni_gallery.html')





def uon_alumni_exec_committee(request):
    executives = Executive.objects.all().order_by('rank')

    
    context = {
        "executives": executives,

    }
    # print(treasurer)
    return render(request, 'home/uon_alumni_exec_committee.html', context)



def uon_alumni_register(request):

    return render(request, 'home/uon_alumni_register.html' )


def uon_alumni_donate(request):
    return render(request, 'home/uon_alumni_donate.html')


def uon_alumni_scholarship(request):
    return render(request, 'home/uon_alumni_scholarship.html')


def uon_alumni_in_memoriam(request):
    return render(request, 'home/uon_alumni_in_memoriam.html')

def uon_alumni_contact_us(request):
    return render(request, 'home/uon_alumni_contact_us.html')


