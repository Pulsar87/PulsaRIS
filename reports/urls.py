from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.report_list, name="report_list"),
    path("study/<uuid:order_id>/", views.study_reports, name="study_reports"),
    path("<uuid:order_id>/create/", views.create_report, name="create_report"),
    path("<uuid:report_id>/view/", views.view_report, name="view_report"),
    path("<uuid:report_id>/edit/", views.edit_report, name="edit_report"),
    path("<uuid:report_id>/delete/", views.delete_report, name="delete_report"),
    path("api/templates/", views.get_report_templates, name="get_report_templates"),
    path("api/save-draft/", views.save_report_draft, name="save_report_draft"),
]
