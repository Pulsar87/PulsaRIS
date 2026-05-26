from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from users.models import User


@login_required
def manage_users(request):
    """View for managing users (admin only)."""
    if not hasattr(request.user, 'role') or request.user.role not in ['ADMIN', 'MANAGER']:
        return redirect('worklist')
    
    users = User.objects.all()
    return render(request, 'users/manage_users.html', {'users': users})

# Create your views here.
