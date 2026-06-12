from django.shortcuts import render

# Create your views here.

def all_uon_staff(request):
    
    context = {

    }
    return render(request, "staff/all_uon_staff.html", context)