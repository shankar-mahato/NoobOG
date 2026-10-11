from django.urls import path

from . import api_views

app_name = "api"

urlpatterns = [
    path("auth/player/register/", api_views.RegistrationView.as_view(), name="player-register"),
    path("auth/vendor/register/", api_views.VendorRegistrationView.as_view(), name="vendor-register"),
    path("auth/player/login/", api_views.LoginView.as_view(), name="player-login"),
    path("auth/vendor/login/", api_views.VendorLoginView.as_view(), name="vendor-login"),
    path("auth/logout/", api_views.LogoutView.as_view(), name="logout"),
    path("venues/", api_views.VenueListView.as_view(), name="venue-list"),
    path("venues/<int:venue_id>/", api_views.VenueDetailView.as_view(), name="venue-detail"),
    path(
        "venues/<int:venue_id>/availability/",
        api_views.VenueAvailabilityView.as_view(),
        name="venue-availability",
    ),
    path(
        "venues/<int:venue_id>/bookings/",
        api_views.VenueBookingCreateView.as_view(),
        name="venue-booking-create",
    ),
    path("player/bookings/", api_views.PlayerBookingsView.as_view(), name="player-bookings"),
    path("vendor/venues/", api_views.VendorVenuesView.as_view(), name="vendor-venues"),
    path(
        "vendor/venues/<int:venue_id>/",
        api_views.VendorVenueDetailView.as_view(),
        name="vendor-venue-detail",
    ),
    path("vendor/bookings/", api_views.VendorBookingsView.as_view(), name="vendor-bookings"),
    path(
        "vendor/bookings/<int:booking_id>/accept/",
        api_views.AcceptBookingView.as_view(),
        name="vendor-booking-accept",
    ),
    path(
        "vendor/bookings/<int:booking_id>/release/",
        api_views.ReleaseBookingView.as_view(),
        name="vendor-booking-release",
    ),
]
