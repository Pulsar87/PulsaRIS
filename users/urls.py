from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("manage-users/", views.manage_users, name="manage_users"),
]
