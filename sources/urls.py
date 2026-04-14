from django.urls import path

from . import views


app_name = "sources"

urlpatterns = [
    path("sources/", views.index, name="index"),
    path("sources/add/", views.add_source, name="add"),
    path("sources/edit/<int:source_id>/", views.edit_source, name="edit"),
    path("sources/delete/<int:source_id>/", views.delete_source, name="delete"),
]
