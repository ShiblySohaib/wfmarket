from django.urls import path

from . import fetch_api, views


app_name = "market"

urlpatterns = [
    path("market/", views.index, name="index"),
    path("market/settings/", views.settings_json, name="settings_json"),
    path("market/settings/update/", views.update_settings, name="settings_update"),
    path("market/settings/page/", views.settings_page, name="settings_page"),
    path("api/fetch", fetch_api.fetch, name="fetch"),
    path("api/fetch/status", fetch_api.fetch_status, name="fetch_status"),
    path("api/fetch/<str:session_id>", fetch_api.fetch_progress, name="fetch_progress"),
    path("api/fetch/<str:session_id>/abort", fetch_api.abort_fetch, name="abort_fetch"),
    path("api/market/toggle-pause/", views.toggle_pause_for_labels, name="toggle_pause"),
]
