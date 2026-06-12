from django.shortcuts import render

# Create your views here.
def all_uon_students(request):
    
    context = {

    }
    return render(request, "student/all_uon_students.html", context)