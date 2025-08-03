from django.urls import path
from . import views

app_name = 'sources'
urlpatterns = [
    path('', views.index, name='index'),
    path('add/', views.add_source, name='add_source'),
    path('edit/<int:source_id>/', views.edit_source, name='edit_source'),
    path('delete/<int:source_id>/', views.delete_source, name='delete_source'),
]
