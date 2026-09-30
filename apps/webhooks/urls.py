from django.urls import path
from .views import PaymentWebhookView, ATDeliveryReceiptView, ATInboundMessageView

urlpatterns = [
    path("webhooks/payments/<str:provider>", PaymentWebhookView.as_view(), name="webhook-payments"),
    path("webhooks/at/delivery", ATDeliveryReceiptView.as_view(), name="webhook-at-delivery"),
    path("webhooks/at/inbound", ATInboundMessageView.as_view(), name="webhook-at-inbound"),
]
