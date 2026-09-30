from django.urls import path
from .views import CollectionPolicyView, CampaignListCreate, CampaignDetail, CampaignLaunchView, CampaignStatsView

urlpatterns = [
    path("collections/policy", CollectionPolicyView.as_view(), name="collection-policy"),
    path("collections/campaigns", CampaignListCreate.as_view(), name="campaign-list-create"),
    path("collections/campaigns/<uuid:pk>", CampaignDetail.as_view(), name="campaign-detail"),
    path("collections/campaigns/<uuid:pk>/launch", CampaignLaunchView.as_view(), name="campaign-launch"),
    path("collections/campaigns/<uuid:pk>/stats", CampaignStatsView.as_view(), name="campaign-stats"),
]
