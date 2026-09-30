from django.urls import path
from .views import CustomerListCreate, CustomerDetail, CustomerLanguageView, CustomerBulkCreateView

urlpatterns = [
    path("customers", CustomerListCreate.as_view(), name="customer-list-create"),
    path("customers/bulk", CustomerBulkCreateView.as_view(), name="customer-bulk"),
    path("customers/<uuid:pk>", CustomerDetail.as_view(), name="customer-detail"),
    path("customers/<uuid:pk>/language", CustomerLanguageView.as_view(), name="customer-language"),
]
