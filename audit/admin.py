from django.contrib import admin
from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = [
        "timestamp",
        "user",
        "action",
        "entity_type",
        "entity_id",
        "ip_address",
    ]
    list_filter = ["action", "entity_type", "timestamp"]
    search_fields = ["entity_id", "user__username", "user__email", "ip_address"]
    readonly_fields = [
        "id",
        "user",
        "action",
        "entity_type",
        "entity_id",
        "old_values",
        "new_values",
        "ip_address",
        "user_agent",
        "timestamp",
    ]
    ordering = ["-timestamp"]
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
