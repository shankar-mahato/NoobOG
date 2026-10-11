from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

from booking import views
from booking.forms import PlayerAuthenticationForm, VendorAuthenticationForm
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def vendor_login(request):
    if request.user.is_authenticated:
        if request.user.role == request.user.Role.VENDOR:
            return redirect("vendor_dashboard")
        return redirect("venue_list")
    return auth_views.LoginView.as_view(
        authentication_form=VendorAuthenticationForm,
        template_name="registration/vendor_login.html",
        next_page="vendor_dashboard",
    )(request)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("booking.urls")),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(authentication_form=PlayerAuthenticationForm),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/signup/", views.player_signup, name="signup"),
    path("vendor/", include("booking.vendor_urls")),
    path(
        "vendor/login/",
        vendor_login,
        name="vendor_login",
    ),
    path("vendor/logout/", auth_views.LogoutView.as_view(), name="vendor_logout"),
    path("vendor/register/", views.vendor_signup, name="vendor_signup"),
    path("api/schema/", SpectacularAPIView.as_view(), name="api_schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api_schema"),
        name="api_docs",
    ),
    path("api/v1/", include("booking.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
