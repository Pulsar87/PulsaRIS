from django.contrib import admin
from django.contrib.auth.models import Group
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin

# Register the default Django Group model
admin.site.register(Group, BaseGroupAdmin)
