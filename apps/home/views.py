from django.shortcuts import render

from apps.home.models import Chapter

# Create your views here.







def uon_alumni_home(request):
    
    context = {

    }
    return render(request, "home/alumni_home.html", context)



def uon_alumni_history(request):
    return render(request, 'home/uon_alumni_history.html')


def uon_alumni_gallery(request):

    
    return render(request, 'home/uon_alumni_gallery.html')