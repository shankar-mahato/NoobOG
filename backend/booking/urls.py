from django.urls import path

from . import views

urlpatterns = [
    path("", views.venue_list, name="venue_list"),
    path("venues/<int:venue_id>/", views.venue_detail, name="venue_detail"),
    path("venues/<int:venue_id>/book/", views.book_slot, name="book_slot"),
    path("reservations/", views.reservation_search, name="reservation_search"),
    path(
        "reservations/results/",
        views.reservation_results,
        name="reservation_results",
    ),
    path(
        "reservations/confirm/",
        views.reservation_confirmation,
        name="reservation_confirmation",
    ),
    path("my-bookings/", views.my_bookings, name="my_bookings"),
    path("favorites/", views.favorites, name="favorites"),
    path(
        "venues/<int:venue_id>/favorite/",
        views.toggle_favorite,
        name="toggle_favorite",
    ),
    path("venues/<int:venue_id>/like/", views.toggle_like, name="toggle_like"),
]
