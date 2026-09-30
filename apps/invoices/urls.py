from django.urls import path
from .views import InvoiceListCreate, InvoiceDetail, InvoicePdfView, InvoicePayLinkView, PublicPayInfoView
from apps.payments.views import PublicPaystackInitializeView, PublicPaystackVerifyView

urlpatterns = [
    path("invoices", InvoiceListCreate.as_view(), name="invoice-list-create"),
    path("invoices/<uuid:pk>", InvoiceDetail.as_view(), name="invoice-detail"),
    path("invoices/<uuid:pk>/pdf", InvoicePdfView.as_view(), name="invoice-pdf"),
    path("invoices/<uuid:pk>/pay-link", InvoicePayLinkView.as_view(), name="invoice-pay-link"),
    path("public/pay/<uuid:pk>", PublicPayInfoView.as_view(), name="public-pay-info"),
    # Public payment initialization — called from the customer /pay/:id page (no auth)
    path("public/pay/<uuid:pk>/initialize", PublicPaystackInitializeView.as_view(), name="public-pay-initialize"),
    path("public/pay/verify", PublicPaystackVerifyView.as_view(), name="public-pay-verify"),
]
