from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("manage-users/", views.manage_users, name="manage_users"),
]
