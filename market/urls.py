from django.urls import path
from . import views

app_name = 'market'

urlpatterns = [
    path('', views.index, name='index'),
    path('fetch-data/', views.fetch_market_data, name='fetch_data'),
]
