from django.urls import path
from .views import SignupView, LoginView, MeView

urlpatterns = [
    path("signup", SignupView.as_view(), name="auth-signup"),
    path("login", LoginView.as_view(), name="auth-login"),
    path("me", MeView.as_view(), name="auth-me"),
]
