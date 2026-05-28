from django.urls import path

from orders import views

app_name = 'orders'

urlpatterns = [
    path('reserve/', views.reserve_order, name='reserve_order'),
]
