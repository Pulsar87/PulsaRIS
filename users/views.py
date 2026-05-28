from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from users.models import User


def user_login(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        user = authenticate(request, username=email, password=password)

        if user is not None:
            login(request, user)
            messages.success(
                request, _("Welcome back, %(username)s!") % {"username": user.username}
            )
            return redirect("home")
        else:
            messages.error(request, _("Invalid email or password."))

    return render(request, "users/login.html")


def user_logout(request):
    """User logout view."""
    logout(request)
    messages.info(request, _("You have been logged out."))
    return redirect("users/login")


@login_required
def manage_users(request):
    """View for managing users (admin only)."""
    if not hasattr(request.user, "role") or request.user.role not in [
        "ADMIN",
        "MANAGER",
    ]:
        return redirect("worklist")

    users = User.objects.all()
    return render(request, "users/manage_users.html", {"users": users})


# Create your views here.
