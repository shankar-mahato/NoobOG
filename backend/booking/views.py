from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.http import HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import PlayerSignUpForm, VendorSignUpForm, VenueForm
from .models import (
    ActivityCategory,
    Booking,
    User,
    Venue,
    VenueFavorite,
    VenueLike,
    VenueVisit,
)
from .services import (
    ACTIVE_BOOKING_STATUSES,
    available_systems as _available_systems,
    daily_schedule as _daily_schedule,
    minutes_after_midnight as _minutes_after_midnight,
    notify_vendor_of_booking,
    peak_bookings as _peak_bookings,
    venue_hours as _venue_hours,
)


def _selected_date(request):
    date_text = request.GET.get("date", "")
    if not date_text:
        return timezone.localdate()
    try:
        selected_date = date.fromisoformat(date_text)
    except ValueError:
        raise ValueError("Choose a valid calendar date.") from None
    if selected_date < timezone.localdate():
        raise ValueError("Choose today or a future date.")
    return selected_date


def vendor_required(view_func):
    @wraps(view_func)
    @login_required(login_url="vendor_login")
    def wrapped(request, *args, **kwargs):
        if request.user.role != User.Role.VENDOR:
            return HttpResponseForbidden("This page is for vendor accounts.")
        return view_func(request, *args, **kwargs)

    return wrapped


def player_required(view_func):
    @wraps(view_func)
    @login_required(login_url="login")
    def wrapped(request, *args, **kwargs):
        if request.user.role != User.Role.PLAYER:
            return HttpResponseForbidden("This action is for player accounts.")
        return view_func(request, *args, **kwargs)

    return wrapped


def player_signup(request):
    if request.user.is_authenticated:
        return redirect("venue_list")
    form = PlayerSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.role = User.Role.PLAYER
        user.save(update_fields=["role"])
        login(request, user)
        return redirect("venue_list")
    return render(request, "registration/signup.html", {"form": form})


def vendor_portal(request):
    if request.user.is_authenticated and request.user.role == User.Role.VENDOR:
        return redirect("vendor_dashboard")
    if request.user.is_authenticated and request.user.role == User.Role.PLAYER:
        return redirect("venue_list")
    return render(request, "booking/vendor_portal.html")


def vendor_signup(request):
    if request.user.is_authenticated:
        if request.user.role == User.Role.VENDOR:
            return redirect("vendor_dashboard")
        return redirect("venue_list")
    form = VendorSignUpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.role = User.Role.VENDOR
        user.save()
        form.save_m2m()
        login(request, user)
        return redirect("vendor_dashboard")
    return render(request, "registration/vendor_signup.html", {"form": form})


def venue_list(request):
    if request.user.is_authenticated and request.user.role == User.Role.VENDOR:
        return redirect("vendor_dashboard")
    venue_filters = Q(is_active=True)
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    activity_categories = ActivityCategory.objects.filter(is_active=True)
    category_labels = {item.slug: item.name for item in activity_categories}
    active_category_slugs = set(category_labels)
    if query:
        venue_filters &= (
            Q(name__icontains=query)
            | Q(location__icontains=query)
            | Q(address_line__icontains=query)
            | Q(city__icontains=query)
            | Q(state__icontains=query)
            | Q(country__icontains=query)
            | Q(postal_code__icontains=query)
            | Q(description__icontains=query)
        )
    if category in active_category_slugs:
        venue_filters &= Q(category=category)
    else:
        category = ""
    venue_filters &= Q(category__in=active_category_slugs)
    venues = Venue.objects.filter(venue_filters).annotate(
        like_count=Count("likes", distinct=True),
    )

    favorite_venue_ids = set()
    liked_venue_ids = set()
    favorites = Venue.objects.none()
    recent_venues = Venue.objects.none()
    recent_venue_ids = list(request.session.get("recent_venue_ids", []))
    if request.user.is_authenticated and request.user.role == User.Role.PLAYER:
        favorite_venue_ids = set(
            VenueFavorite.objects.filter(player=request.user).values_list(
                "venue_id",
                flat=True,
            )
        )
        liked_venue_ids = set(
            VenueLike.objects.filter(player=request.user).values_list("venue_id", flat=True)
        )
        favorites = (
            Venue.objects.filter(venue_filters)
            .filter(
                Q(favorites__player=request.user)
                | Q(likes__player=request.user),
            )
            .annotate(like_count=Count("likes", distinct=True))
            .distinct()
            .order_by("-like_count", "name")[:6]
        )
        recent_visits = list(
            VenueVisit.objects.filter(player=request.user, venue__is_active=True)
            .values("venue_id")
            .annotate(last_visited=Max("visited_at"))
            .order_by("-last_visited")[:6]
        )
        for visit in recent_visits:
            venue_id = visit["venue_id"]
            if venue_id not in recent_venue_ids:
                recent_venue_ids.append(venue_id)
        recent_venue_ids = recent_venue_ids[:6]
    elif request.user.is_authenticated:
        recent_venue_ids = []

    if recent_venue_ids:
        recent_venue_map = {
            venue.pk: venue
            for venue in Venue.objects.filter(
                venue_filters,
                pk__in=recent_venue_ids,
            ).annotate(like_count=Count("likes", distinct=True))
        }
        recent_venues = [
            recent_venue_map[venue_id]
            for venue_id in recent_venue_ids
            if venue_id in recent_venue_map
        ]

    popular_venues = Venue.objects.none()
    if not request.user.is_authenticated:
        popular_venues = (
            Venue.objects.filter(venue_filters)
            .annotate(like_count=Count("likes", distinct=True))
            .order_by("-like_count", "-created_at")[:6]
        )
    return render(
        request,
        "booking/venue_list.html",
        {
            "venues": venues,
            "query": query,
            "selected_category": category,
            "selected_category_label": category_labels.get(category, ""),
            "categories": activity_categories,
            "favorite_venue_ids": favorite_venue_ids,
            "liked_venue_ids": liked_venue_ids,
            "favorites": favorites,
            "recent_venues": recent_venues,
            "popular_venues": popular_venues,
        },
    )


def venue_detail(request, venue_id):
    venues = Venue.objects.filter(is_active=True).select_related("owner").annotate(
        like_count=Count("likes", distinct=True),
    )
    is_vendor_view = (
        request.user.is_authenticated
        and request.user.role == User.Role.VENDOR
    )
    if is_vendor_view:
        venues = venues.filter(owner=request.user)
    else:
        venues = venues.filter(
            category__in=ActivityCategory.objects.filter(
                is_active=True,
            ).values_list("slug", flat=True)
        )
    venue = get_object_or_404(venues, pk=venue_id)
    if not request.user.is_authenticated or request.user.role == User.Role.PLAYER:
        recent_venue_ids = request.session.get("recent_venue_ids", [])
        recent_venue_ids = [venue.pk] + [
            visited_id for visited_id in recent_venue_ids if visited_id != venue.pk
        ]
        request.session["recent_venue_ids"] = recent_venue_ids[:6]
        if request.user.is_authenticated:
            VenueVisit.objects.create(player=request.user, venue=venue)
    is_favorite = False
    is_liked = False
    if request.user.is_authenticated and request.user.role == User.Role.PLAYER:
        is_favorite = VenueFavorite.objects.filter(
            player=request.user,
            venue=venue,
        ).exists()
        is_liked = VenueLike.objects.filter(
            player=request.user,
            venue=venue,
        ).exists()
    try:
        selected_date = _selected_date(request)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    closing_label = (
        "midnight"
        if venue.closing_time == time(0, 0)
        else venue.closing_time.strftime("%I:%M %p").lstrip("0")
    )
    return render(
        request,
        "booking/venue_detail.html",
        {
            "venue": venue,
            "today": timezone.localdate(),
            "selected_date": selected_date,
            "schedule": _daily_schedule(venue, selected_date),
            "is_vendor_view": is_vendor_view,
            "is_favorite": is_favorite,
            "is_liked": is_liked,
            "closing_label": closing_label,
        },
    )


def reservation_search(request):
    if request.user.is_authenticated and request.user.role == User.Role.VENDOR:
        return redirect("vendor_dashboard")
    try:
        selected_date = _selected_date(request)
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    selected_venue = None
    venue_id = request.GET.get("venue", "")
    if venue_id:
        try:
            venue_id = int(venue_id)
        except ValueError:
            return HttpResponseBadRequest("Choose a valid venue.")
        active_category_slugs = ActivityCategory.objects.filter(
            is_active=True,
        ).values_list("slug", flat=True)
        selected_venue = get_object_or_404(
            Venue,
            pk=venue_id,
            is_active=True,
            category__in=active_category_slugs,
        )

    category = request.GET.get("category", "")
    if selected_venue:
        category = selected_venue.category
    active_categories = ActivityCategory.objects.filter(is_active=True)
    category_labels = {item.slug: item.name for item in active_categories}
    if category not in category_labels:
        category = ""
    category_label = category_labels.get(category, "All activities")
    try:
        duration_minutes = int(request.GET.get("duration_minutes", "60"))
    except ValueError:
        duration_minutes = 60
    if duration_minutes not in (60, 90, 120):
        duration_minutes = 60
    if not request.GET.get("date"):
        venues = Venue.objects.filter(
            is_active=True,
            category__in=category_labels,
        )
        if selected_venue:
            venues = venues.filter(pk=selected_venue.pk)
        elif category:
            venues = venues.filter(category=category)
        has_available_session_today = any(
            any(
                option["minutes"] == duration_minutes
                for row in _daily_schedule(venue, selected_date)
                for option in row["options"]
            )
            for venue in venues
        )
        if not has_available_session_today:
            selected_date += timedelta(days=1)
    return render(
        request,
        "booking/reservation_search.html",
        {
            "selected_category": category,
            "category_label": category_label,
            "selected_venue": selected_venue,
            "selected_date": selected_date,
            "today": timezone.localdate(),
            "duration_minutes": duration_minutes,
        },
    )


def reservation_results(request):
    if request.user.is_authenticated and request.user.role == User.Role.VENDOR:
        return redirect("vendor_dashboard")
    try:
        selected_date = _selected_date(request)
        duration_minutes = int(request.GET.get("duration_minutes", "60"))
    except ValueError as error:
        return HttpResponseBadRequest(str(error))
    if duration_minutes not in (60, 90, 120):
        return HttpResponseBadRequest("Choose a supported session duration.")
    category = request.GET.get("category", "")
    active_categories = ActivityCategory.objects.filter(is_active=True)
    category_labels = {item.slug: item.name for item in active_categories}
    if category and category not in category_labels:
        return HttpResponseBadRequest("Choose a valid activity.")

    selected_venue = None
    venue_filters = Q(is_active=True, category__in=category_labels)
    venue_id = request.GET.get("venue", "")
    if venue_id:
        try:
            venue_id = int(venue_id)
        except ValueError:
            return HttpResponseBadRequest("Choose a valid venue.")
        selected_venue = get_object_or_404(
            Venue,
            pk=venue_id,
            is_active=True,
            category__in=category_labels,
        )
        if category and category != selected_venue.category:
            return HttpResponseBadRequest("The selected venue does not match this activity.")
        category = selected_venue.category
        venue_filters &= Q(pk=selected_venue.pk)
    elif category:
        venue_filters &= Q(category=category)
    venues = Venue.objects.filter(venue_filters).select_related("owner")
    results = []
    for venue in venues:
        for row in _daily_schedule(venue, selected_date):
            duration_option = next(
                (
                    option
                    for option in row["options"]
                    if option["minutes"] == duration_minutes
                ),
                None,
            )
            if duration_option is None:
                continue
            start_time = row["start"]
            confirmation_query = urlencode(
                {
                    "venue": venue.pk,
                    "category": venue.category,
                    "date": selected_date.isoformat(),
                    "start_time": start_time.strftime("%H:%M"),
                    "duration_minutes": duration_minutes,
                }
            )
            results.append(
                {
                    "venue": venue,
                    "start_time": start_time,
                    "end_time": (
                        datetime.combine(selected_date, start_time)
                        + timedelta(minutes=duration_minutes)
                    ).time(),
                    "units_left": duration_option["systems_left"],
                    "confirmation_url": (
                        f"{reverse('reservation_confirmation')}?{confirmation_query}"
                    ),
                }
            )
    results.sort(key=lambda result: (result["start_time"], result["venue"].name.casefold()))
    return render(
        request,
        "booking/reservation_results.html",
        {
            "results": results,
            "total_slots": len(results),
            "selected_date": selected_date,
            "duration_minutes": duration_minutes,
            "duration_label": (
                "1.5 hours" if duration_minutes == 90 else f"{duration_minutes // 60} hour"
                f"{'s' if duration_minutes != 60 else ''}"
            ),
            "category": category,
            "category_label": category_labels.get(category, "All activities"),
            "selected_venue": selected_venue,
            "next_date_url": reverse("reservation_results")
            + "?"
            + urlencode(
                {
                    "category": category,
                    "venue": venue_id,
                    "date": (selected_date + timedelta(days=1)).isoformat(),
                    "duration_minutes": duration_minutes,
                }
            ),
        },
    )


def reservation_confirmation(request):
    if request.user.is_authenticated and request.user.role == User.Role.VENDOR:
        return redirect("vendor_dashboard")
    try:
        venue_id = int(request.GET.get("venue", ""))
        selected_date = _selected_date(request)
        start_time = time.fromisoformat(request.GET.get("start_time", ""))
        duration_minutes = int(request.GET.get("duration_minutes", ""))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Choose a valid venue, date, time, and duration.")
    start_minute = _minutes_after_midnight(start_time)
    if (
        duration_minutes not in (60, 90, 120)
        or start_time.minute not in (0, 30)
        or start_time.second != 0
    ):
        return HttpResponseBadRequest("Choose a valid available session.")
    venue = get_object_or_404(
        Venue,
        pk=venue_id,
        is_active=True,
        category__in=ActivityCategory.objects.filter(
            is_active=True,
        ).values_list("slug", flat=True),
    )
    opening_minute, closing_minute = _venue_hours(venue)
    if (
        start_minute < opening_minute
        or start_minute + duration_minutes > closing_minute
        or (start_minute - opening_minute) % duration_minutes
    ):
        return HttpResponseBadRequest(
            "Choose a session start aligned to the selected duration within this venue's opening hours."
        )
    schedule_row = next(
        (
            row
            for row in _daily_schedule(venue, selected_date)
            if row["start"] == start_time
        ),
        None,
    )
    duration_option = next(
        (
            option
            for option in schedule_row["options"]
            if option["minutes"] == duration_minutes
        ),
        None,
    ) if schedule_row else None
    if duration_option is None:
        messages.error(request, "That session is no longer available. Please choose another.")
        return redirect(
            f"{reverse('reservation_results')}?{urlencode(request.GET.dict())}"
        )

    fee = (
        Decimal(venue.hourly_rate) * Decimal(duration_minutes) / Decimal(60)
    ).quantize(Decimal("0.01"))
    return render(
        request,
        "booking/reservation_confirmation.html",
        {
            "venue": venue,
            "selected_date": selected_date,
            "start_time": start_time,
            "end_time": (
                datetime.combine(selected_date, start_time)
                + timedelta(minutes=duration_minutes)
            ).time(),
            "duration_minutes": duration_minutes,
            "duration_label": (
                "1.5 hours" if duration_minutes == 90 else f"{duration_minutes // 60} hour"
                f"{'s' if duration_minutes != 60 else ''}"
            ),
            "units_left": duration_option["systems_left"],
            "resource_type": venue.activity_category.resource_label,
            "host_name": (
                venue.owner.get_full_name().strip() or venue.owner.username
            ),
            "host_fee": fee,
            "total_fee": fee,
            "today": timezone.localdate(),
        },
    )


@player_required
def book_slot(request, venue_id):
    if request.method != "POST":
        return redirect("venue_detail", venue_id=venue_id)

    try:
        game_date = date.fromisoformat(request.POST.get("game_date", ""))
        start_time = time.fromisoformat(request.POST.get("start_time", ""))
        raw_duration_minutes = request.POST.get("duration_minutes")
        if raw_duration_minutes:
            duration_minutes = int(raw_duration_minutes)
            if duration_minutes not in (60, 90, 120):
                raise ValueError
        else:
            duration_hours = int(request.POST.get("duration_hours", ""))
            if duration_hours < 1:
                raise ValueError
            duration_minutes = duration_hours * 60
    except (TypeError, ValueError):
        messages.error(request, "Choose a valid date, start time, and session length.")
        return redirect("venue_detail", venue_id=venue_id)

    start_minute = _minutes_after_midnight(start_time)
    if (
        game_date < timezone.localdate()
        or start_time.second != 0
        or (
            game_date == timezone.localdate()
            and start_time <= timezone.localtime().time()
        )
    ):
        messages.error(request, "Choose an available future time between 10 AM and midnight.")
        return redirect(
            f"{reverse('venue_detail', args=[venue_id])}?date={game_date.isoformat()}"
        )

    try:
        with transaction.atomic():
            venue = get_object_or_404(
                Venue.objects.select_for_update(),
                pk=venue_id,
                is_active=True,
            )
            opening_minute, closing_minute = _venue_hours(venue)
            if (
                start_minute < opening_minute
                or start_minute + duration_minutes > closing_minute
                or (start_minute - opening_minute) % duration_minutes
            ):
                messages.error(
                    request,
                    "Choose a session start aligned to the selected duration within this venue's opening hours.",
                )
                return redirect(
                    f"{reverse('venue_detail', args=[venue_id])}?date={game_date.isoformat()}"
                )
            bookings = list(
                Booking.objects.filter(
                    venue=venue,
                    game_date=game_date,
                    status__in=ACTIVE_BOOKING_STATUSES,
                ).values_list("player_id", "start_time", "duration_minutes")
            )
            intervals = [
                (_minutes_after_midnight(booked_start), duration)
                for _, booked_start, duration in bookings
            ]
            player_intervals = [
                (_minutes_after_midnight(booked_start), duration)
                for player_id, booked_start, duration in bookings
                if player_id == request.user.pk
            ]
            if any(
                booked_start < start_minute + duration_minutes
                and booked_start + duration > start_minute
                for booked_start, duration in player_intervals
            ):
                messages.info(request, "You already have a booking overlapping that time.")
            elif not _available_systems(
                venue,
                intervals,
                start_minute,
                duration_minutes,
            ):
                messages.error(request, "Those hours are no longer available. Choose another time.")
            else:
                booking = Booking.objects.create(
                    player=request.user,
                    venue=venue,
                    game_date=game_date,
                    start_time=start_time,
                    duration_minutes=duration_minutes,
                    status=Booking.Status.PENDING,
                )
                transaction.on_commit(
                    lambda booking_id=booking.pk: notify_vendor_of_booking(
                        request,
                        booking_id,
                    )
                )
                messages.success(
                    request,
                    f"Booking request {booking.reference_code} sent. The vendor will confirm your session.",
                )
    except IntegrityError:
        messages.info(request, "You already have a booking starting at that time.")
    return redirect(
        f"{reverse('venue_detail', args=[venue_id])}?date={game_date.isoformat()}"
    )


@player_required
def my_bookings(request):
    bookings = Booking.objects.filter(player=request.user).select_related("venue")
    return render(request, "booking/my_bookings.html", {"bookings": bookings})


def favorites(request):
    if request.user.is_authenticated and request.user.role == User.Role.VENDOR:
        return redirect("vendor_dashboard")
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={reverse('favorites')}")
    favorite_venue_ids = set(
        VenueFavorite.objects.filter(player=request.user).values_list("venue_id", flat=True)
    )
    liked_venue_ids = set(
        VenueLike.objects.filter(player=request.user).values_list("venue_id", flat=True)
    )
    venues = Venue.objects.filter(
        favorites__player=request.user,
        is_active=True,
    ).annotate(like_count=Count("likes", distinct=True))
    return render(
        request,
        "booking/venue_collection.html",
        {
            "venues": venues,
            "heading": "Your favorites",
            "eyebrow": "SAVED PLACES",
            "favorite_venue_ids": favorite_venue_ids,
            "liked_venue_ids": liked_venue_ids,
        },
    )


def _player_action_redirect(request):
    referer = request.META.get("HTTP_REFERER", "")
    if url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        return redirect(referer)
    return redirect("venue_list")


@player_required
def toggle_favorite(request, venue_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Use POST to update favorites.")
    venue = get_object_or_404(Venue, pk=venue_id, is_active=True)
    favorite, created = VenueFavorite.objects.get_or_create(
        player=request.user,
        venue=venue,
    )
    if not created:
        favorite.delete()
        messages.success(request, f"{venue.name} removed from your favorites.")
    else:
        messages.success(request, f"{venue.name} added to your favorites.")
    return _player_action_redirect(request)


@player_required
def toggle_like(request, venue_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Use POST to update likes.")
    venue = get_object_or_404(Venue, pk=venue_id, is_active=True)
    like, created = VenueLike.objects.get_or_create(
        player=request.user,
        venue=venue,
    )
    if not created:
        like.delete()
    return _player_action_redirect(request)


@vendor_required
def vendor_dashboard(request):
    venues = (
        Venue.objects.filter(owner=request.user)
        .annotate(
            booking_count=Count(
                "bookings",
                filter=Q(bookings__status__in=ACTIVE_BOOKING_STATUSES),
            ),
            pending_count=Count(
                "bookings",
                filter=Q(bookings__status=Booking.Status.PENDING),
            ),
        )
        .order_by("name")
    )
    pending_count = Booking.objects.filter(
        venue__owner=request.user,
        status=Booking.Status.PENDING,
    ).count()
    return render(
        request,
        "booking/vendor_dashboard.html",
        {"venues": venues, "pending_count": pending_count},
    )


@vendor_required
def vendor_bookings(request):
    bookings = Booking.objects.filter(
        venue__owner=request.user,
    ).exclude(status=Booking.Status.CANCELLED).select_related(
        "player",
        "venue",
    )
    return render(
        request,
        "booking/vendor_bookings.html",
        {
            "bookings": bookings,
            "pending_count": bookings.filter(status=Booking.Status.PENDING).count(),
        },
    )


@vendor_required
def accept_booking(request, booking_id):
    if request.method != "POST":
        return redirect("vendor_bookings")
    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_related("venue").select_for_update(),
            pk=booking_id,
            venue__owner=request.user,
        )
        if booking.status != Booking.Status.PENDING:
            messages.info(request, "This booking request is no longer awaiting approval.")
        else:
            intervals = [
                (_minutes_after_midnight(start_time), duration)
                for start_time, duration in Booking.objects.filter(
                    venue=booking.venue,
                    game_date=booking.game_date,
                    status__in=ACTIVE_BOOKING_STATUSES,
                ).values_list("start_time", "duration_minutes")
            ]
            if _peak_bookings(
                intervals,
                _minutes_after_midnight(booking.start_time),
                _minutes_after_midnight(booking.start_time) + booking.duration_minutes,
            ) > booking.venue.system_count:
                messages.error(
                    request,
                    "There are not enough bookable units for this booking. Increase the venue's unit count or release a booking.",
                )
            else:
                booking.status = Booking.Status.CONFIRMED
                booking.save(update_fields=["status"])
                messages.success(request, "Booking accepted.")
    return redirect("vendor_bookings")


@vendor_required
def release_booking(request, booking_id):
    if request.method != "POST":
        return redirect("vendor_bookings")
    with transaction.atomic():
        booking = get_object_or_404(
            Booking.objects.select_related("venue").select_for_update(),
            pk=booking_id,
            venue__owner=request.user,
        )
        if booking.status == Booking.Status.CANCELLED:
            messages.info(request, "This booking has already been released.")
        else:
            booking.status = Booking.Status.CANCELLED
            booking.save(update_fields=["status"])
            messages.success(request, "Booking released. The system is available again.")
    return redirect("vendor_bookings")


@vendor_required
def venue_create(request):
    form = VenueForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        venue = form.save(commit=False)
        venue.owner = request.user
        venue.save()
        messages.success(request, "Your venue is now listed.")
        return redirect("vendor_dashboard")
    return render(request, "booking/venue_form.html", {"form": form, "is_edit": False})


@vendor_required
def venue_edit(request, venue_id):
    venue = get_object_or_404(Venue, pk=venue_id, owner=request.user)
    form = VenueForm(request.POST or None, request.FILES or None, instance=venue)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Venue details updated.")
        return redirect("vendor_dashboard")
    return render(
        request,
        "booking/venue_form.html",
        {"form": form, "venue": venue, "is_edit": True},
    )
