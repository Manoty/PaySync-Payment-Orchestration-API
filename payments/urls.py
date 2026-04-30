from django.urls import path
from .views import (
    InitiatePaymentView,
    PaymentDetailView,
    PaymentListView,
)

app_name = 'payments'

urlpatterns = [
    # Initiate a new payment
    path('payments/initiate/', InitiatePaymentView.as_view(), name='initiate'),

    # List all payments (with optional filters)
    path('payments/', PaymentListView.as_view(), name='list'),

    # Get specific payment by internal reference (UUID)
    path('payments/<uuid:reference>/', PaymentDetailView.as_view(), name='detail'),
]