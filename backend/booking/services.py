import logging
import smtplib
from datetime import time

from django.contrib import messages
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from .models import Booking

logger = logging.getLogger(__name__)
ACTIVE_BOOKING_STATUSES = [Booking.Status.PENDING, Booking.Status.CONFIRMED]


def minutes_after_midnight(value):
    return value.hour * 60 + value.minute


def venue_hours(venue):
    opening_minute = minutes_after_midnight(venue.opening_time)
    closing_minute = minutes_after_midnight(venue.closing_time)
    if closing_minute == 0:
        closing_minute = 24 * 60
    return opening_minute, closing_minute


def peak_bookings(bookings, start_minute, end_minute):
    change_points = {start_minute}
    change_points.update(
        booked_start
        for booked_start, _ in bookings
        if start_minute < booked_start < end_minute
    )
    return max(
        (
            sum(
                booked_start <= point < booked_start + duration
                for booked_start, duration in bookings
            )
            for point in change_points
        ),
        default=0,
    )


def available_systems(venue, bookings, start_minute, duration_minutes):
    end_minute = start_minute + duration_minutes
    return max(
        0,
        venue.system_count - peak_bookings(bookings, start_minute, end_minute),
    )


def daily_schedule(venue, selected_date):
    existing = Booking.objects.filter(
        venue=venue,
        game_date=selected_date,
        status__in=ACTIVE_BOOKING_STATUSES,
    ).values_list("start_time", "duration_minutes")
    intervals = [
        (minutes_after_midnight(start_time), duration)
        for start_time, duration in existing
    ]
    now = timezone.localtime().time()
    opening_minute, closing_minute = venue_hours(venue)
    schedule_by_start = {}
    for duration_minutes in (60, 90, 120):
        for start_minute in range(
            opening_minute,
            closing_minute - duration_minutes + 1,
            duration_minutes,
        ):
            start = time(hour=start_minute // 60, minute=start_minute % 60)
            if selected_date == timezone.localdate() and start <= now:
                continue
            systems_left = available_systems(
                venue,
                intervals,
                start_minute,
                duration_minutes,
            )
            if not systems_left:
                continue
            row = schedule_by_start.setdefault(
                start_minute,
                {"start": start, "options": [], "systems_left": 0},
            )
            row["options"].append(
                {
                    "minutes": duration_minutes,
                    "hours": duration_minutes / 60,
                    "systems_left": systems_left,
                }
            )
            if duration_minutes == 60:
                row["systems_left"] = systems_left

    schedule = []
    for start_minute in sorted(schedule_by_start):
        row = schedule_by_start[start_minute]
        start = row["start"]
        schedule.append(row)
    return schedule


def notify_vendor_of_booking(request, booking_id):
    booking = Booking.objects.select_related("venue__owner", "player").get(pk=booking_id)
    vendor = booking.venue.owner
    if not vendor.email:
        messages.warning(
            request,
            "Your request is saved, but this venue has no vendor email address. The vendor can still see it in their dashboard.",
        )
        logger.warning("Vendor %s has no email for booking %s", vendor.pk, booking.pk)
        return
    try:
        vendor_bookings_url = request.build_absolute_uri(reverse("vendor_bookings"))
        send_mail(
            subject=f"New NoobOG booking request — {booking.venue.name}",
            message=(
                f"{booking.player.username} requested a gaming session at "
                f"{booking.venue.name} on "
                f"{booking.game_date:%A, %B %-d} at "
                f"{booking.start_time:%I:%M %p} for {booking.duration_label}.\n\n"
                f"Review and accept or release the request in your NoobOG vendor dashboard:\n"
                f"{vendor_bookings_url}"
            ),
            from_email=None,
            recipient_list=[vendor.email],
            fail_silently=False,
        )
    except (OSError, smtplib.SMTPException, ValueError):
        logger.exception("Could not email vendor %s about booking %s", vendor.pk, booking.pk)
        messages.warning(
            request,
            "Your request is saved, but the vendor email notification could not be sent. It remains visible in the vendor dashboard.",
        )
