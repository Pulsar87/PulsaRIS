"""
URL Configuration for Insurance/Payer Master Data Management API
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import ClearinghouseViewSet, InsurancePayerViewSet

router = DefaultRouter()
router.register(r'clearinghouses', ClearinghouseViewSet, basename='clearinghouse')
router.register(r'payers', InsurancePayerViewSet, basename='payer')

urlpatterns = [
    path('', include(router.urls)),
]
