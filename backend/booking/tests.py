from datetime import datetime, time, timedelta
from io import BytesIO
import json
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image
from django.core.exceptions import ValidationError
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from .models import (
    ActivityCategory,
    Booking,
    User,
    Venue,
    VenueFavorite,
    VenueLike,
    VenueVisit,
)


class NoobOGFlowTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username="vendor",
            password="strong-pass-123",
            email="vendor@example.com",
            role=User.Role.VENDOR,
        )
        self.player = User.objects.create_user(
            username="player",
            password="strong-pass-123",
            role=User.Role.PLAYER,
        )
        self.venue = Venue.objects.create(
            owner=self.vendor,
            name="Checkpoint Social",
            location="Koramangala, Bengaluru",
            address_line="42 Koramangala Main Road",
            city="Bengaluru",
            state="Karnataka",
            country="India",
            postal_code="560034",
            category="pc",
            hourly_rate=249,
            system_count=1,
        )
        self.future_date = timezone.localdate() + timedelta(days=1)

    def create_booking(
        self,
        *,
        player=None,
        start_hour=10,
        duration_hours=1,
        status=Booking.Status.PENDING,
        venue=None,
        game_date=None,
    ):
        return Booking.objects.create(
            player=player or self.player,
            venue=venue or self.venue,
            game_date=game_date or self.future_date,
            start_time=time(hour=start_hour),
            duration_minutes=duration_hours * 60,
            status=status,
        )

    def make_venue_image(self, name="venue.png"):
        image_data = BytesIO()
        Image.new("RGB", (2, 2), color="green").save(image_data, format="PNG")
        return SimpleUploadedFile(
            name,
            image_data.getvalue(),
            content_type="image/png",
        )

    def test_venue_listing_can_be_searched_and_filtered(self):
        response = self.client.get(
            reverse("venue_list"),
            {"q": "Koramangala", "category": "pc"},
        )

        self.assertContains(response, "NoobOG")
        self.assertNotContains(response, "PlaySlot")
        self.assertContains(response, "Checkpoint Social")
        self.assertContains(response, "Koramangala")

    def test_venue_search_matches_postal_code(self):
        response = self.client.get(reverse("venue_list"), {"q": "560034"})

        self.assertContains(response, "Checkpoint Social")
        self.assertContains(response, "560034")

    def test_venue_search_matches_city_state_and_country(self):
        for term in ("Bengaluru", "Karnataka", "India"):
            with self.subTest(term=term):
                response = self.client.get(reverse("venue_list"), {"q": term})
                self.assertContains(response, "Checkpoint Social")

    def test_structured_venue_address_is_shown_on_public_detail_and_cards(self):
        detail = self.client.get(reverse("venue_detail", args=[self.venue.pk]))
        listing = self.client.get(reverse("venue_list"))

        self.assertContains(
            detail,
            "42 Koramangala Main Road, Bengaluru, Karnataka, 560034, India",
        )
        self.assertContains(
            listing,
            "42 Koramangala Main Road, Bengaluru, Karnataka, 560034, India",
        )

    def test_legacy_venue_address_falls_back_to_existing_location(self):
        self.venue.address_line = ""
        self.venue.city = ""
        self.venue.state = ""
        self.venue.country = ""

        self.assertEqual(self.venue.display_address, "Koramangala, Bengaluru, 560034")

    def test_my_bookings_lists_booked_venue(self):
        booking = self.create_booking()
        self.client.force_login(self.player)

        response = self.client.get(reverse("my_bookings"))

        self.assertContains(response, "My bookings")
        self.assertContains(response, self.venue.name)
        self.assertContains(response, booking.get_status_display().upper())

    def test_player_navigation_and_marketplace_hide_vendor_interface(self):
        self.client.force_login(self.player)

        response = self.client.get(reverse("venue_list"))
        login_response = self.client.get(reverse("login"))

        self.assertContains(response, "Find a venue")
        self.assertNotContains(response, ">Reservations</a>")
        self.assertContains(response, "Favorites")
        self.assertContains(response, "My bookings")
        self.assertNotContains(response, "For parlours")
        self.assertNotContains(response, "List your venue")
        self.assertNotContains(response, 'href="/vendor/"')
        self.assertNotContains(login_response, "vendor portal")

    def test_player_is_redirected_away_from_vendor_portal_and_auth_pages(self):
        self.client.force_login(self.player)

        for route_name in ("vendor_portal", "vendor_signup", "vendor_login"):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse("venue_list"))

    def test_vendor_navigation_hides_player_interface(self):
        self.client.force_login(self.vendor)

        response = self.client.get(reverse("vendor_dashboard"))

        self.assertContains(response, "Vendor studio")
        self.assertContains(response, "Bookings")
        self.assertContains(response, "Your venues. Your bookings.")
        self.assertNotContains(response, "Find a venue")
        self.assertNotContains(response, "Reservations")
        self.assertNotContains(response, "Favorites")
        self.assertNotContains(response, "My bookings")
        self.assertNotContains(response, 'href="/"')

    def test_guest_navigation_has_no_reservations_menu(self):
        response = self.client.get(reverse("venue_list"))

        self.assertNotContains(response, ">Reservations</a>")

    def test_activity_slider_filters_venues_by_new_activity_type(self):
        snooker_venue = Venue.objects.create(
            owner=self.vendor,
            name="Corner Pocket",
            location="Indiranagar",
            category="snooker",
            hourly_rate=300,
        )

        response = self.client.get(reverse("venue_list"), {"category": "snooker"})

        self.assertContains(response, "Corner Pocket")
        self.assertNotContains(response, "Checkpoint Social")
        self.assertEqual(list(response.context["venues"]), [snooker_venue])
        self.assertContains(response, "Swimming pool")

    def test_activity_categories_are_seeded_and_admin_managed(self):
        self.assertTrue(
            ActivityCategory.objects.filter(
                slug="pc",
                name="PC gaming",
                resource_label="Gaming station",
                is_active=True,
            ).exists()
        )
        self.client.force_login(
            User.objects.create_superuser(
                username="category-admin",
                email="category-admin@example.com",
                password="Valid-pass-739!",
            )
        )

        response = self.client.get("/admin/booking/activitycategory/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PC gaming")

    def test_admin_managed_category_appears_in_player_and_vendor_forms(self):
        custom_category = ActivityCategory.objects.create(
            slug="pickleball",
            name="Pickleball",
            resource_label="Pickleball court",
            icon="🏓",
            sort_order=5,
        )
        custom_venue = Venue.objects.create(
            owner=self.vendor,
            name="Court Club",
            location="Bengaluru",
            category=custom_category.slug,
            hourly_rate=400,
        )
        self.client.force_login(self.vendor)
        vendor_form = self.client.get(reverse("venue_create"))
        self.client.logout()
        listing = self.client.get(reverse("venue_list"))

        self.assertContains(vendor_form, "Pickleball")
        self.assertContains(listing, "Pickleball")
        self.assertContains(listing, "🏓")
        self.assertContains(listing, custom_venue.name)
        self.assertTrue(
            listing.context["categories"].filter(pk=custom_category.pk).exists()
        )

    def test_category_slug_cannot_change_while_venues_use_it(self):
        category = ActivityCategory.objects.get(slug="pc")
        category.slug = "gaming"

        with self.assertRaisesMessage(
            ValidationError,
            "The slug cannot change while venues use this category.",
        ):
            category.full_clean()

    def test_vendor_can_keep_an_inactive_category_on_existing_venue(self):
        ActivityCategory.objects.filter(slug="pc").update(is_active=False)
        self.client.force_login(self.vendor)

        response = self.client.get(reverse("venue_edit", args=[self.venue.pk]))

        self.assertContains(response, '<option value="pc" selected>')
        self.assertContains(response, "PC gaming")

    def test_disabling_category_hides_its_venues_from_players(self):
        ActivityCategory.objects.filter(slug="pc").update(is_active=False)

        listing = self.client.get(reverse("venue_list"))
        detail = self.client.get(reverse("venue_detail", args=[self.venue.pk]))
        results = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "60",
            },
        )

        self.assertNotContains(listing, self.venue.name)
        self.assertEqual(detail.status_code, 404)
        self.assertEqual(results.status_code, 400)

    def test_recently_viewed_venues_appear_on_homepage_for_guest(self):
        self.client.get(reverse("venue_detail", args=[self.venue.pk]))

        response = self.client.get(reverse("venue_list"))

        self.assertContains(response, "Recently viewed")
        self.assertContains(response, self.venue.name)

    def test_guest_sees_global_most_liked_venues(self):
        VenueLike.objects.create(player=self.player, venue=self.venue)

        response = self.client.get(reverse("venue_list"))

        self.assertContains(response, "Most liked venues")
        self.assertEqual(list(response.context["popular_venues"]), [self.venue])

    def test_signed_in_player_sees_only_their_liked_or_saved_venues(self):
        another_venue = Venue.objects.create(
            owner=self.vendor,
            name="Another Arena",
            location="Elsewhere",
            category="pc",
            hourly_rate=300,
        )
        other_player = User.objects.create_user(
            username="another-player",
            password="Valid-pass-739!",
            role=User.Role.PLAYER,
        )
        VenueLike.objects.create(player=self.player, venue=self.venue)
        VenueFavorite.objects.create(player=other_player, venue=another_venue)
        VenueLike.objects.create(player=other_player, venue=another_venue)
        self.client.force_login(self.player)

        response = self.client.get(reverse("venue_list"))

        self.assertEqual(
            {venue.pk for venue in response.context["favorites"]},
            {self.venue.pk},
        )
        self.assertContains(response, "Venues you like")
        self.assertContains(response, self.venue.name)
        self.assertNotContains(response, "Most liked venues")

    def test_player_venue_views_are_recorded_without_showing_recent_section(self):
        self.client.force_login(self.player)
        self.client.get(reverse("venue_detail", args=[self.venue.pk]))

        response = self.client.get(reverse("venue_list"))

        self.assertTrue(
            VenueVisit.objects.filter(player=self.player, venue=self.venue).exists()
        )
        self.assertNotContains(response, "Recently viewed")

    def test_player_can_save_and_unsave_favorite_venues(self):
        self.client.force_login(self.player)
        detail_url = reverse("venue_detail", args=[self.venue.pk])

        self.client.post(reverse("toggle_favorite", args=[self.venue.pk]), HTTP_REFERER=detail_url)
        self.assertTrue(
            VenueFavorite.objects.filter(player=self.player, venue=self.venue).exists()
        )
        favorites_page = self.client.get(reverse("favorites"))
        self.assertContains(favorites_page, self.venue.name)
        self.assertContains(self.client.get(reverse("venue_list")), "Venues you like")

        self.client.post(reverse("toggle_favorite", args=[self.venue.pk]), HTTP_REFERER=detail_url)
        self.assertFalse(
            VenueFavorite.objects.filter(player=self.player, venue=self.venue).exists()
        )

    def test_player_likes_venues_and_guest_homepage_orders_popular_by_likes(self):
        another_venue = Venue.objects.create(
            owner=self.vendor,
            name="Second Arena",
            location="Bengaluru",
            category="console",
            hourly_rate=199,
        )
        self.client.force_login(self.player)

        self.client.post(reverse("toggle_like", args=[self.venue.pk]))
        self.client.post(reverse("toggle_like", args=[self.venue.pk]))

        self.assertEqual(
            VenueLike.objects.filter(player=self.player, venue=self.venue).count(),
            0,
        )
        self.client.post(reverse("toggle_like", args=[self.venue.pk]))
        VenueLike.objects.create(
            player=User.objects.create_user(
                username="liker",
                password="like-test-123",
                role=User.Role.PLAYER,
            ),
            venue=self.venue,
        )
        response = self.client.get(reverse("venue_list"))
        personal = list(response.context["favorites"])
        self.assertEqual(personal, [self.venue])
        self.assertNotContains(response, "Most liked venues")

        self.client.logout()
        guest_response = self.client.get(reverse("venue_list"))
        popular = list(guest_response.context["popular_venues"])
        self.assertEqual(popular[0], self.venue)
        self.assertIn(another_venue, popular)
        self.assertContains(guest_response, "Most liked venues")

    def test_automatic_schedule_uses_duration_intervals(self):
        response = self.client.get(
            reverse("venue_detail", args=[self.venue.pk]),
            {"date": self.future_date.isoformat()},
        )

        self.assertEqual(len(response.context["schedule"]), 13)
        first_start = response.context["schedule"][0]
        self.assertEqual(first_start["start"].hour, 10)
        self.assertEqual(first_start["start"].minute, 0)
        self.assertEqual(first_start["options"][0]["hours"], 1)
        self.assertEqual(
            [option["minutes"] for option in first_start["options"]],
            [60, 90, 120],
        )
        self.assertEqual(first_start["options"][-1]["hours"], 2)
        self.assertEqual(response.context["schedule"][-1]["start"], time(19, 0))
        self.assertEqual(
            [option["minutes"] for option in response.context["schedule"][-1]["options"]],
            [60],
        )
        self.assertEqual(response.context["schedule"][-1]["systems_left"], 1)
        self.assertContains(response, "10:00 AM")
        self.assertContains(response, "8:00 PM")

    def test_venue_detail_links_to_reservation_search(self):
        response = self.client.get(
            reverse("venue_detail", args=[self.venue.pk]),
            {"date": self.future_date.isoformat()},
        )

        self.assertContains(response, "Find a session")
        self.assertContains(response, reverse("reservation_search"))
        self.assertContains(
            response,
            f"?venue={self.venue.pk}&category={self.venue.category}",
        )

    def test_venue_reservation_search_keeps_selected_venue(self):
        response = self.client.get(
            reverse("reservation_search"),
            {"venue": self.venue.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_venue"], self.venue)
        self.assertContains(response, self.venue.name)
        self.assertContains(response, f'name="venue" value="{self.venue.pk}"')

    def test_venue_reservation_results_only_include_selected_venue_sessions(self):
        another_venue = Venue.objects.create(
            owner=self.vendor,
            name="Another PC Venue",
            location="Elsewhere",
            category="pc",
            hourly_rate=300,
        )

        response = self.client.get(
            reverse("reservation_results"),
            {
                "venue": self.venue.pk,
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "60",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {result["venue"].pk for result in response.context["results"]},
            {self.venue.pk},
        )
        self.assertContains(response, self.venue.name)
        self.assertNotContains(response, another_venue.name)
        self.assertContains(response, f"venue={self.venue.pk}")

    def test_venue_reservation_search_defaults_date_using_selected_venue_only(self):
        all_night_venue = Venue.objects.create(
            owner=self.vendor,
            name="All Night PC Venue",
            location="Elsewhere",
            category="pc",
            hourly_rate=300,
            closing_time=time(0, 0),
        )
        late_today = timezone.make_aware(
            datetime.combine(self.future_date, time(23, 10)),
            timezone.get_current_timezone(),
        )
        self.assertEqual(all_night_venue.category, self.venue.category)
        with (
            patch("booking.services.timezone.localdate", return_value=self.future_date),
            patch("booking.services.timezone.localtime", return_value=late_today),
        ):
            response = self.client.get(
                reverse("reservation_search"),
                {"venue": self.venue.pk},
            )

        self.assertEqual(
            response.context["selected_date"],
            self.future_date + timedelta(days=1),
        )

    def test_reservation_search_renders_filter_form_and_duration_options(self):
        response = self.client.get(
            reverse("reservation_search"),
            {"category": "pc", "date": self.future_date.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reservations")
        self.assertContains(response, 'name="category"')
        self.assertContains(response, 'name="date"')
        self.assertContains(response, 'value="60"')
        self.assertContains(response, 'value="90"')
        self.assertContains(response, 'value="120"')
        self.assertContains(response, "PC gaming")
        self.assertNotContains(response, "Advanced options")
        self.assertNotContains(response, "HOST")
        self.assertNotContains(response, '<select name="category"')

    def test_reservation_search_defaults_to_tomorrow_when_today_has_no_sessions(self):
        late_today = timezone.make_aware(
            datetime.combine(self.future_date, time(23, 10)),
            timezone.get_current_timezone(),
        )
        with (
            patch("booking.services.timezone.localdate", return_value=self.future_date),
            patch("booking.services.timezone.localtime", return_value=late_today),
        ):
            response = self.client.get(
                reverse("reservation_search"),
                {"category": "pc"},
            )

        self.assertEqual(
            response.context["selected_date"],
            self.future_date + timedelta(days=1),
        )

    def test_reservation_search_preserves_an_explicit_today_selection(self):
        late_today = timezone.make_aware(
            datetime.combine(self.future_date, time(23, 10)),
            timezone.get_current_timezone(),
        )
        with (
            patch("booking.services.timezone.localdate", return_value=self.future_date),
            patch("booking.services.timezone.localtime", return_value=late_today),
        ):
            response = self.client.get(
                reverse("reservation_search"),
                {
                    "category": "pc",
                    "date": self.future_date.isoformat(),
                },
            )

        self.assertEqual(response.context["selected_date"], self.future_date)

    def test_empty_session_results_offer_the_next_day(self):
        late_today = timezone.make_aware(
            datetime.combine(self.future_date, time(23, 10)),
            timezone.get_current_timezone(),
        )
        with (
            patch("booking.services.timezone.localdate", return_value=self.future_date),
            patch("booking.services.timezone.localtime", return_value=late_today),
        ):
            response = self.client.get(
                reverse("reservation_results"),
                {
                    "category": "pc",
                    "date": self.future_date.isoformat(),
                    "duration_minutes": "60",
                },
            )

        self.assertEqual(response.context["total_slots"], 0)
        self.assertContains(response, "No sessions available for this date")
        self.assertContains(response, "Check the next day")
        self.assertContains(
            response,
            f"date={self.future_date + timedelta(days=1)}",
        )

    def test_reservation_results_include_only_sessions_within_venue_hours(self):
        response = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "60",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_slots"], 10)
        self.assertContains(response, "10:00 – 11:00 AM")
        self.assertNotContains(response, "10:30 – 11:30 AM")
        self.assertContains(response, "11:00 – 12:00 PM")
        self.assertContains(response, "7:00 – 8:00 PM")
        self.assertNotContains(response, "7:30 – 8:30 PM")
        self.assertContains(response, reverse("reservation_confirmation"))

    def test_one_hour_sessions_reach_closing_time(self):
        self.venue.closing_time = time(21, 0)
        self.venue.save(update_fields=["closing_time"])
        response = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "60",
            },
        )

        self.assertEqual(response.context["total_slots"], 11)
        self.assertContains(response, "10:00 – 11:00 AM")
        self.assertContains(response, "8:00 – 9:00 PM")
        self.assertNotContains(response, "9:00 – 10:00 PM")

    def test_duration_results_step_by_selected_duration(self):
        self.venue.closing_time = time(21, 0)
        self.venue.save(update_fields=["closing_time"])
        response = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "90",
            },
        )

        self.assertEqual(response.context["total_slots"], 7)
        self.assertContains(response, "10:00 – 11:30 AM")
        self.assertContains(response, "11:30 – 1:00 PM")
        self.assertContains(response, "1:00 – 2:30 PM")
        self.assertContains(response, "7:00 – 8:30 PM")
        self.assertNotContains(response, "8:30 – 10:00 PM")

    def test_duration_results_skip_sessions_overlapping_existing_booking(self):
        self.venue.closing_time = time(21, 0)
        self.venue.save(update_fields=["closing_time"])
        Booking.objects.create(
            player=self.player,
            venue=self.venue,
            game_date=self.future_date,
            start_time=time(11, 30),
            duration_minutes=90,
            status=Booking.Status.PENDING,
        )
        response = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "90",
            },
        )

        self.assertEqual(response.context["total_slots"], 6)
        self.assertContains(response, "10:00 – 11:30 AM")
        self.assertNotContains(response, "11:30 – 1:00 PM")
        self.assertContains(response, "1:00 – 2:30 PM")

    def test_reservation_results_hide_booked_sessions(self):
        self.create_booking(start_hour=10)
        response = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "60",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_slots"], 9)
        self.assertNotContains(response, "10:00 – 11:00 AM")
        self.assertNotContains(response, "10:30 – 11:30 AM")
        self.assertContains(response, "11:00 – 12:00 PM")

    def test_two_hour_results_fit_within_configured_closing_time(self):
        response = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "120",
            },
        )

        self.assertEqual(response.context["total_slots"], 5)
        self.assertContains(response, "6:00 – 8:00 PM")
        self.assertNotContains(response, "6:30 – 8:30 PM")

    def test_vendor_can_change_business_hours_and_generated_sessions_update(self):
        self.client.force_login(self.vendor)
        edit_page = self.client.get(reverse("venue_edit", args=[self.venue.pk]))
        self.assertContains(edit_page, "Complete address line")
        self.assertContains(edit_page, 'name="city"')
        self.assertContains(edit_page, 'name="state"')
        self.assertContains(edit_page, 'name="country"')
        self.assertContains(edit_page, "Opens at")
        self.assertContains(edit_page, "Closes at")
        self.assertContains(edit_page, 'name="opening_time"')
        self.assertContains(edit_page, 'name="closing_time"')

        response = self.client.post(
            reverse("venue_edit", args=[self.venue.pk]),
            {
                "name": self.venue.name,
                "address_line": self.venue.address_line,
                "city": self.venue.city,
                "state": self.venue.state,
                "country": self.venue.country,
                "postal_code": self.venue.postal_code,
                "category": self.venue.category,
                "description": self.venue.description,
                "hourly_rate": self.venue.hourly_rate,
                "system_count": self.venue.system_count,
                "opening_time": "11:00",
                "closing_time": "20:00",
            },
            follow=True,
        )

        self.venue.refresh_from_db()
        self.assertEqual(self.venue.opening_time, time(11, 0))
        self.assertEqual(self.venue.closing_time, time(20, 0))
        schedule_response = self.client.get(
            reverse("venue_detail", args=[self.venue.pk]),
            {"date": self.future_date.isoformat()},
        )
        self.assertContains(schedule_response, "11:00 AM")
        self.assertContains(schedule_response, "8:00 PM")
        self.client.logout()
        results = self.client.get(
            reverse("reservation_results"),
            {
                "category": "pc",
                "date": self.future_date.isoformat(),
                "duration_minutes": "60",
            },
        )
        self.assertEqual(results.context["total_slots"], 9)

    def test_vendor_cannot_shorten_hours_past_an_active_booking(self):
        self.venue.closing_time = time(0, 0)
        self.venue.save(update_fields=["closing_time"])
        self.create_booking(start_hour=22, duration_hours=2)
        self.client.force_login(self.vendor)

        response = self.client.post(
            reverse("venue_edit", args=[self.venue.pk]),
            {
                "name": self.venue.name,
                "address_line": self.venue.address_line,
                "city": self.venue.city,
                "state": self.venue.state,
                "country": self.venue.country,
                "postal_code": self.venue.postal_code,
                "category": self.venue.category,
                "description": self.venue.description,
                "hourly_rate": self.venue.hourly_rate,
                "system_count": self.venue.system_count,
                "opening_time": "10:00",
                "closing_time": "20:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hours cannot change to exclude an active booking.")
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.closing_time, time(0, 0))

    def test_reservation_confirmation_shows_fee_summary_and_reserve_action(self):
        response = self.client.get(
            reverse("reservation_confirmation"),
            {
                "venue": self.venue.pk,
                "date": self.future_date.isoformat(),
                "start_time": "11:30",
                "duration_minutes": "90",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SERVICE LOCATION")
        self.assertContains(response, "RESOURCE TYPE")
        self.assertContains(response, "HOST FEE")
        self.assertContains(response, "TOTAL FEE")
        self.assertContains(response, "₹373.50")

    def test_player_can_reserve_duration_aligned_start(self):
        self.client.force_login(self.player)
        response = self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "11:30",
                "duration_minutes": "90",
            },
            follow=True,
        )

        booking = Booking.objects.get(player=self.player, venue=self.venue)
        self.assertEqual(booking.start_time, time(11, 30))
        self.assertEqual(booking.duration_minutes, 90)
        self.assertContains(response, "vendor will confirm your session")
        self.assertContains(response, booking.reference_code)

    def test_player_booking_list_shows_assigned_reference_code(self):
        booking = self.create_booking(start_hour=10)
        self.client.force_login(self.player)

        response = self.client.get(reverse("my_bookings"))

        self.assertContains(response, "Booking ID:")
        self.assertContains(response, booking.reference_code)

    def test_player_can_choose_multi_hour_booking(self):
        self.client.force_login(self.player)

        response = self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "10:00",
                "duration_hours": "3",
            },
            follow=True,
        )

        booking = Booking.objects.get(player=self.player, venue=self.venue)
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertEqual(booking.duration_minutes, 180)
        self.assertContains(response, "vendor will confirm your session")

    def test_player_can_book_one_and_a_half_hours(self):
        self.client.force_login(self.player)

        response = self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "10:00",
                "duration_minutes": "90",
            },
            follow=True,
        )

        booking = Booking.objects.get(player=self.player, venue=self.venue)
        self.assertEqual(booking.duration_minutes, 90)
        self.assertEqual(booking.duration_label, "1.5 hours")
        self.assertContains(response, "vendor will confirm your session")

    def test_invalid_duration_minutes_are_rejected(self):
        self.client.force_login(self.player)

        self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "10:00",
                "duration_minutes": "75",
            },
        )

        self.assertFalse(Booking.objects.filter(player=self.player).exists())

    def test_pending_booking_holds_overlapping_hours_from_players(self):
        self.create_booking(start_hour=10, duration_hours=2)
        response = self.client.get(
            reverse("venue_detail", args=[self.venue.pk]),
            {"date": self.future_date.isoformat()},
        )

        schedule = response.context["schedule"]
        self.assertNotIn(time(10, 0), [row["start"] for row in schedule])
        self.assertNotIn(time(11, 0), [row["start"] for row in schedule])
        at_noon = next(row for row in schedule if row["start"].hour == 12)
        self.assertEqual(at_noon["systems_left"], 1)

    def test_multiple_systems_allow_overlapping_sessions_up_to_capacity(self):
        self.venue.system_count = 2
        self.venue.save(update_fields=["system_count"])
        first_player = self.player
        second_player = User.objects.create_user(
            username="second",
            password="strong-pass-123",
            role=User.Role.PLAYER,
        )
        self.create_booking(player=first_player, start_hour=10, duration_hours=2)
        self.client.force_login(second_player)

        response = self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "11:00",
                "duration_hours": "1",
            },
            follow=True,
        )

        self.assertTrue(
            Booking.objects.filter(
                player=second_player,
                venue=self.venue,
                status=Booking.Status.PENDING,
            ).exists()
        )
        booking = Booking.objects.get(player=second_player, venue=self.venue)
        self.assertContains(response, f"Booking request {booking.reference_code} sent.")

    def test_booking_is_rejected_when_all_systems_overlap(self):
        self.create_booking(start_hour=10, duration_hours=2)
        another_player = User.objects.create_user(
            username="another-player",
            password="strong-pass-123",
            role=User.Role.PLAYER,
        )
        self.client.force_login(another_player)

        response = self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "11:00",
                "duration_hours": "1",
            },
            follow=True,
        )

        self.assertFalse(Booking.objects.filter(player=another_player).exists())
        self.assertContains(response, "Those hours are no longer available.")

    def test_booking_cannot_end_after_midnight(self):
        self.client.force_login(self.player)

        self.client.post(
            reverse("book_slot", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "23:00",
                "duration_hours": "2",
            },
        )

        self.assertFalse(Booking.objects.filter(player=self.player).exists())

    def test_vendor_dashboard_only_lists_their_venues(self):
        other_vendor = User.objects.create_user(
            username="other-vendor",
            password="strong-pass-123",
            role=User.Role.VENDOR,
        )
        Venue.objects.create(
            owner=other_vendor,
            name="Other Vendor Arena",
            location="Another place",
            category="console",
            hourly_rate=150,
        )
        self.client.force_login(self.vendor)

        response = self.client.get(reverse("vendor_dashboard"))

        self.assertContains(response, "Checkpoint Social")
        self.assertNotContains(response, "Other Vendor Arena")

    def test_vendor_can_upload_and_update_venue_photo(self):
        self.client.force_login(self.vendor)
        edit_url = reverse("venue_edit", args=[self.venue.pk])
        form_data = {
            "name": self.venue.name,
            "address_line": self.venue.address_line,
            "city": self.venue.city,
            "state": self.venue.state,
            "country": self.venue.country,
            "postal_code": self.venue.postal_code,
            "category": self.venue.category,
            "description": self.venue.description,
            "hourly_rate": self.venue.hourly_rate,
            "system_count": self.venue.system_count,
            "opening_time": "10:00",
            "closing_time": "20:00",
        }

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            edit_page = self.client.get(edit_url)
            self.assertContains(edit_page, "Upload a JPG, PNG, GIF, or WebP image up to 5 MB.")
            self.assertContains(edit_page, 'enctype="multipart/form-data"')

            response = self.client.post(
                edit_url,
                {**form_data, "photo": self.make_venue_image()},
                follow=True,
            )

            self.venue.refresh_from_db()
            self.assertTrue(self.venue.photo.name.startswith("venue-images/"))
            self.assertContains(response, "Venue details updated.")
            self.assertContains(response, self.venue.photo.url)

            response = self.client.post(
                edit_url,
                {**form_data, "photo": self.make_venue_image("venue-updated.png")},
                follow=True,
            )
            self.venue.refresh_from_db()
            self.assertTrue(self.venue.photo.name.endswith("venue-updated.png"))
            self.assertContains(response, "Venue details updated.")

            self.client.logout()
            detail = self.client.get(reverse("venue_detail", args=[self.venue.pk]))
            listing = self.client.get(reverse("venue_list"))
            self.assertContains(detail, self.venue.photo.url)
            self.assertContains(listing, self.venue.photo.url)

    def test_vendor_photo_upload_rejects_files_over_five_megabytes(self):
        self.client.force_login(self.vendor)
        response = self.client.post(
            reverse("venue_edit", args=[self.venue.pk]),
            {
                "name": self.venue.name,
                "address_line": self.venue.address_line,
                "city": self.venue.city,
                "state": self.venue.state,
                "country": self.venue.country,
                "postal_code": self.venue.postal_code,
                "category": self.venue.category,
                "description": self.venue.description,
                "hourly_rate": self.venue.hourly_rate,
                "system_count": self.venue.system_count,
                "opening_time": "10:00",
                "closing_time": "20:00",
                "photo": SimpleUploadedFile(
                    "too-large.png",
                    b"x" * (5 * 1024 * 1024 + 1),
                    content_type="image/png",
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Venue images must be 5 MB or smaller.")
        self.venue.refresh_from_db()
        self.assertFalse(self.venue.photo)

    def test_vendor_cannot_open_public_venue_directory_or_other_store(self):
        other_vendor = User.objects.create_user(
            username="other-vendor",
            password="strong-pass-123",
            role=User.Role.VENDOR,
        )
        other_venue = Venue.objects.create(
            owner=other_vendor,
            name="Other Vendor Arena",
            location="Another place",
            category="console",
            hourly_rate=150,
        )
        self.client.force_login(self.vendor)

        directory_response = self.client.get(reverse("venue_list"))
        other_store_response = self.client.get(
            reverse("venue_detail", args=[other_venue.pk]),
        )

        self.assertRedirects(directory_response, reverse("vendor_dashboard"))
        self.assertEqual(other_store_response.status_code, 404)

    def test_vendor_can_view_only_their_own_daily_schedule(self):
        self.client.force_login(self.vendor)

        response = self.client.get(
            reverse("venue_detail", args=[self.venue.pk]),
            {"date": self.future_date.isoformat()},
        )

        self.assertContains(response, "Daily availability")
        self.assertContains(response, "3 durations available")
        self.assertContains(response, "1 duration available")
        self.assertNotContains(response, "Request ↗")

    def test_vendor_can_accept_and_release_booking(self):
        booking = self.create_booking()
        self.client.force_login(self.vendor)

        self.client.post(reverse("accept_booking", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CONFIRMED)

        self.client.post(reverse("release_booking", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.CANCELLED)

    def test_vendor_booking_actions_are_scoped_to_their_venues(self):
        booking = self.create_booking()
        other_vendor = User.objects.create_user(
            username="other-vendor",
            password="strong-pass-123",
            role=User.Role.VENDOR,
        )
        self.client.force_login(other_vendor)

        response = self.client.post(reverse("accept_booking", args=[booking.pk]))

        self.assertEqual(response.status_code, 404)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING)

    def test_new_request_sends_email_to_venue_vendor(self):
        self.client.force_login(self.player)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(
                reverse("book_slot", args=[self.venue.pk]),
                {
                    "game_date": self.future_date.isoformat(),
                    "start_time": "10:00",
                    "duration_hours": "2",
                },
            )

        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["vendor@example.com"])
        self.assertIn("for 2 hours", mail.outbox[0].body)

    def test_vendor_sets_system_count_for_automatic_availability(self):
        self.client.force_login(self.vendor)

        response = self.client.post(
            reverse("venue_edit", args=[self.venue.pk]),
            {
                "name": self.venue.name,
                "address_line": self.venue.address_line,
                "city": self.venue.city,
                "state": self.venue.state,
                "country": self.venue.country,
                "category": self.venue.category,
                "description": self.venue.description,
                "hourly_rate": self.venue.hourly_rate,
                "system_count": 4,
                "opening_time": "10:00",
                "closing_time": "20:00",
            },
            follow=True,
        )

        self.venue.refresh_from_db()
        self.assertEqual(self.venue.system_count, 4)
        self.assertContains(response, "4")

    def test_vendor_cannot_accept_booking_after_system_count_reduced(self):
        self.venue.system_count = 1
        self.venue.save(update_fields=["system_count"])
        self.create_booking(start_hour=10, duration_hours=1)
        booking = self.create_booking(
            player=User.objects.create_user(
                username="second-player",
                password="strong-pass-123",
                role=User.Role.PLAYER,
            ),
            start_hour=10,
            duration_hours=1,
        )
        self.venue.system_count = 1
        self.venue.save(update_fields=["system_count"])
        self.client.force_login(self.vendor)

        response = self.client.post(
            reverse("accept_booking", args=[booking.pk]),
            follow=True,
        )

        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.PENDING)
        self.assertContains(response, "not enough bookable units")

    def test_vendor_routes_remain_in_vendor_namespace(self):
        self.assertEqual(reverse("vendor_dashboard"), "/vendor/dashboard/")
        self.assertEqual(reverse("vendor_bookings"), "/vendor/bookings/")
        self.assertEqual(reverse("venue_create"), "/vendor/venues/new/")
        self.assertEqual(
            reverse("venue_edit", args=[self.venue.pk]),
            f"/vendor/venues/{self.venue.pk}/edit/",
        )

    def test_vendor_booking_desk_shows_assigned_reference_code(self):
        booking = self.create_booking(start_hour=10)
        self.client.force_login(self.vendor)

        response = self.client.get(reverse("vendor_bookings"))

        self.assertContains(response, "Booking ID:")
        self.assertContains(response, booking.reference_code)


class NoobOGApiTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username="api-vendor",
            password="api-test-pass-741!",
            email="api-vendor@example.com",
            role=User.Role.VENDOR,
        )
        self.player = User.objects.create_user(
            username="api-player",
            password="api-test-pass-741!",
            email="api-player@example.com",
            role=User.Role.PLAYER,
        )
        self.venue = Venue.objects.create(
            owner=self.vendor,
            name="API Arena",
            location="Bengaluru",
            address_line="10 MG Road",
            city="Bengaluru",
            state="Karnataka",
            country="India",
            postal_code="560001",
            category="pc",
            hourly_rate=200,
            system_count=2,
        )
        self.future_date = timezone.localdate() + timedelta(days=1)
        self.client = APIClient()

    def test_openapi_schema_and_swagger_ui_are_available(self):
        schema = self.client.get(f"{reverse('api_schema')}?format=json")
        docs = self.client.get(reverse("api_docs"))

        self.assertEqual(schema.status_code, 200)
        schema_document = json.loads(schema.content)
        self.assertIn("/api/v1/venues/", schema_document["paths"])
        self.assertIn(
            "/api/v1/vendor/bookings/{booking_id}/accept/",
            schema_document["paths"],
        )
        self.assertEqual(docs.status_code, 200)
        self.assertContains(docs, "SwaggerUIBundle")

    def test_player_registration_and_login_return_token(self):
        response = self.client.post(
            reverse("api:player-register"),
            {
                "username": "registered-player",
                "email": "registered@example.com",
                "password": "Valid-pass-739!",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["user"]["role"], User.Role.PLAYER)

        login_response = self.client.post(
            reverse("api:player-login"),
            {"username": "registered-player", "password": "Valid-pass-739!"},
            format="json",
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.data["token"], response.data["token"])

    def test_vendor_registration_uses_vendor_role_and_vendor_login(self):
        register = self.client.post(
            reverse("api:vendor-register"),
            {
                "username": "registered-vendor",
                "email": "registered-vendor@example.com",
                "password": "Valid-pass-739!",
            },
            format="json",
        )
        self.assertEqual(register.status_code, 201)
        self.assertEqual(register.data["user"]["role"], User.Role.VENDOR)

        login = self.client.post(
            reverse("api:vendor-login"),
            {"username": "registered-vendor", "password": "Valid-pass-739!"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data["user"]["role"], User.Role.VENDOR)

    def test_availability_api_returns_date_and_available_durations(self):
        response = self.client.get(
            reverse("api:venue-availability", args=[self.venue.pk]),
            {"date": self.future_date.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["date"], self.future_date)
        self.assertEqual(response.data["opening_time"], "10:00")
        self.assertEqual(response.data["closing_time"], "20:00")
        first_slot = response.data["slots"][0]
        self.assertEqual(first_slot["start_time"], "10:00:00")
        self.assertEqual(
            [duration["minutes"] for duration in first_slot["durations"]],
            [60, 90, 120],
        )
        self.assertEqual(first_slot["durations"][-1]["hours"], 2)

    def test_venue_api_searches_postal_code_and_activity_category(self):
        self.venue.category = "snooker"
        self.venue.save(update_fields=["category"])

        response = self.client.get(
            reverse("api:venue-list"),
            {"q": self.venue.postal_code, "category": "snooker"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.data], [self.venue.pk])
        self.assertEqual(response.data[0]["postal_code"], self.venue.postal_code)

    def test_venue_api_exposes_structured_address_fields(self):
        response = self.client.get(
            reverse("api:venue-detail", args=[self.venue.pk]),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["address_line"], "10 MG Road")
        self.assertEqual(response.data["city"], "Bengaluru")
        self.assertEqual(response.data["state"], "Karnataka")
        self.assertEqual(response.data["country"], "India")

    def test_player_can_book_available_session_and_vendor_can_accept(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.player).key}")
        booking_response = self.client.post(
            reverse("api:venue-booking-create", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "10:00",
                "duration_hours": 2,
            },
            format="json",
        )

        self.assertEqual(booking_response.status_code, 201)
        self.assertEqual(booking_response.data["status"], Booking.Status.PENDING)
        self.assertEqual(
            booking_response.data["reference_code"],
            f"PS-{booking_response.data['id']:06d}",
        )
        self.assertEqual(
            booking_response.data["venue_location"],
            "10 MG Road, Bengaluru, Karnataka, 560001, India",
        )
        booking_id = booking_response.data["id"]

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.vendor).key}"
        )
        accept_response = self.client.post(
            reverse("api:vendor-booking-accept", args=[booking_id]),
            format="json",
        )
        self.assertEqual(accept_response.status_code, 200)
        self.assertEqual(accept_response.data["status"], Booking.Status.CONFIRMED)

    def test_api_player_can_book_one_and_a_half_hours(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.player).key}"
        )
        response = self.client.post(
            reverse("api:venue-booking-create", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "10:00",
                "duration_hours": 1.5,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["duration_minutes"], 90)
        self.assertEqual(response.data["duration_hours"], 1.5)

    def test_api_accepts_starts_aligned_to_session_duration(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.player).key}"
        )
        response = self.client.post(
            reverse("api:venue-booking-create", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "11:00",
                "duration_hours": 1,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["start_time"], "11:00:00")

    def test_api_rejects_starts_not_aligned_to_duration(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.player).key}"
        )
        response = self.client.post(
            reverse("api:venue-booking-create", args=[self.venue.pk]),
            {
                "game_date": self.future_date.isoformat(),
                "start_time": "10:30",
                "duration_hours": 1,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("aligned", str(response.data))

    def test_vendor_api_only_exposes_owned_venues(self):
        other_vendor = User.objects.create_user(
            username="other-api-vendor",
            password="api-test-pass-741!",
            role=User.Role.VENDOR,
        )
        other_venue = Venue.objects.create(
            owner=other_vendor,
            name="Private Arena",
            location="Elsewhere",
            category="vr",
            hourly_rate=300,
        )
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.vendor).key}"
        )

        venues = self.client.get(reverse("api:vendor-venues"))
        private_venue = self.client.get(
            reverse("api:vendor-venue-detail", args=[other_venue.pk])
        )

        self.assertEqual(venues.status_code, 200)
        self.assertEqual([venue["id"] for venue in venues.data], [self.venue.pk])
        self.assertEqual(private_venue.status_code, 404)

    def test_vendor_api_can_set_operating_hours(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.vendor).key}"
        )
        response = self.client.patch(
            reverse("api:vendor-venue-detail", args=[self.venue.pk]),
            {"opening_time": "10:00:00", "closing_time": "20:00:00"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["opening_time"], "10:00:00")
        self.assertEqual(response.data["closing_time"], "20:00:00")
        self.venue.refresh_from_db()
        self.assertEqual(self.venue.closing_time, time(20, 0))

    def test_vendor_api_can_upload_venue_photo(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.vendor).key}"
        )
        image_data = BytesIO()
        Image.new("RGB", (2, 2), color="blue").save(image_data, format="PNG")

        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.patch(
                reverse("api:vendor-venue-detail", args=[self.venue.pk]),
                {
                    "photo": SimpleUploadedFile(
                        "api-venue.png",
                        image_data.getvalue(),
                        content_type="image/png",
                    )
                },
                format="multipart",
            )

            self.assertEqual(response.status_code, 200)
            self.assertIn("venue-images/", response.data["photo"])
            self.venue.refresh_from_db()
            self.assertTrue(self.venue.photo.name.endswith("api-venue.png"))

    def test_player_token_cannot_access_vendor_management(self):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.player).key}"
        )

        response = self.client.get(reverse("api:vendor-venues"))

        self.assertEqual(response.status_code, 403)
