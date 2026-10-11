from django.urls import path

from . import views

urlpatterns = [
    path("", views.vendor_portal, name="vendor_portal"),
    path("dashboard/", views.vendor_dashboard, name="vendor_dashboard"),
    path("bookings/", views.vendor_bookings, name="vendor_bookings"),
    path(
        "bookings/<int:booking_id>/accept/",
        views.accept_booking,
        name="accept_booking",
    ),
    path(
        "bookings/<int:booking_id>/release/",
        views.release_booking,
        name="release_booking",
    ),
    path("venues/new/", views.venue_create, name="venue_create"),
    path("venues/<int:venue_id>/edit/", views.venue_edit, name="venue_edit"),
]
