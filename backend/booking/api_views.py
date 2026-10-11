from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .api_permissions import IsPlayer, IsVendor
from .api_serializers import (
    AccountRegistrationSerializer,
    AvailabilityQuerySerializer,
    VenueAvailabilitySerializer,
    BookingRequestSerializer,
    BookingSerializer,
    LoginRequestSerializer,
    TokenResponseSerializer,
    VenueSerializer,
)
from .models import ActivityCategory, Booking, User, Venue
from .services import (
    ACTIVE_BOOKING_STATUSES,
    available_systems,
    daily_schedule,
    minutes_after_midnight,
    notify_vendor_of_booking,
    venue_hours,
)


class RegistrationView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    role = User.Role.PLAYER

    @extend_schema(
        request=AccountRegistrationSerializer,
        responses={201: TokenResponseSerializer},
        tags=["Authentication"],
        description="Create the account type served by this endpoint and return its token.",
    )
    def post(self, request):
        serializer = AccountRegistrationSerializer(
            data=request.data,
            context={"role": self.role},
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": {
                    "id": user.pk,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                },
            },
            status=status.HTTP_201_CREATED,
        )


class VendorRegistrationView(RegistrationView):
    role = User.Role.VENDOR


class LoginView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    role = User.Role.PLAYER

    @extend_schema(
        request=LoginRequestSerializer,
        responses={200: TokenResponseSerializer},
        tags=["Authentication"],
        description="Authenticate the player or vendor account served by this login endpoint.",
    )
    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")
        user = authenticate(request, username=username, password=password)
        if not user or user.role != self.role:
            return Response(
                {"detail": f"Invalid {self.role} username or password."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": {
                    "id": user.pk,
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                },
            }
        )


class VendorLoginView(LoginView):
    role = User.Role.VENDOR


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={204: None},
        tags=["Authentication"],
        description="Revoke the current token.",
    )
    def post(self, request):
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class VenueListView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "q",
                str,
                description="Search venue name, area, postal code, or description.",
            ),
            OpenApiParameter(
                "category",
                str,
                description="Filter by an active activity category slug managed in Django admin.",
            ),
        ],
        responses=VenueSerializer(many=True),
        tags=["Venues"],
    )
    def get(self, request):
        active_category_slugs = ActivityCategory.objects.filter(
            is_active=True,
        ).values_list("slug", flat=True)
        venues = Venue.objects.filter(
            is_active=True,
            category__in=active_category_slugs,
        )
        query = request.query_params.get("q", "").strip()
        category = request.query_params.get("category", "").strip()
        if query:
            venues = venues.filter(
                Q(name__icontains=query)
                | Q(location__icontains=query)
                | Q(address_line__icontains=query)
                | Q(city__icontains=query)
                | Q(state__icontains=query)
                | Q(country__icontains=query)
                | Q(postal_code__icontains=query)
                | Q(description__icontains=query)
            )
        if category and ActivityCategory.objects.filter(
            slug=category,
            is_active=True,
        ).exists():
            venues = venues.filter(category=category)
        elif category:
            venues = Venue.objects.none()
        venues = venues.filter(
            category__in=ActivityCategory.objects.filter(
                is_active=True,
            ).values_list("slug", flat=True)
        )
        return Response(VenueSerializer(venues, many=True).data)


class VenueDetailView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(responses=VenueSerializer, tags=["Venues"])
    def get(self, request, venue_id):
        venue = get_object_or_404(
            Venue,
            pk=venue_id,
            is_active=True,
            category__in=ActivityCategory.objects.filter(
                is_active=True,
            ).values_list("slug", flat=True),
        )
        return Response(VenueSerializer(venue).data)


class VenueAvailabilityView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "date",
                str,
                description="ISO date (YYYY-MM-DD). Defaults to today.",
            )
        ],
        responses=VenueAvailabilitySerializer,
        tags=["Availability"],
    )
    def get(self, request, venue_id):
        venue = get_object_or_404(
            Venue,
            pk=venue_id,
            is_active=True,
            category__in=ActivityCategory.objects.filter(
                is_active=True,
            ).values_list("slug", flat=True),
        )
        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        selected_date = query.validated_data.get("date", timezone.localdate())
        slots = []
        for item in daily_schedule(venue, selected_date):
            slots.append(
                {
                    "start_time": item["start"].isoformat(),
                    "systems_left": item["systems_left"],
                    "durations": item["options"],
                }
            )
        return Response(
            {
                "venue": venue.pk,
                "date": selected_date,
                "opening_time": venue.opening_time.strftime("%H:%M"),
                "closing_time": (
                    "24:00"
                    if venue.closing_time.hour == 0 and venue.closing_time.minute == 0
                    else venue.closing_time.strftime("%H:%M")
                ),
                "slots": slots,
            }
        )


class VenueBookingCreateView(APIView):
    permission_classes = [IsAuthenticated, IsPlayer]

    @extend_schema(
        request=BookingRequestSerializer,
        responses={201: BookingSerializer},
        tags=["Player bookings"],
        description="Create a pending booking request. It holds one system until the vendor responds.",
    )
    def post(self, request, venue_id):
        data = BookingRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            with transaction.atomic():
                venue = get_object_or_404(
                    Venue.objects.select_for_update(),
                    pk=venue_id,
                    is_active=True,
                    category__in=ActivityCategory.objects.filter(
                        is_active=True,
                    ).values_list("slug", flat=True),
                )
                game_date = data.validated_data["game_date"]
                start_time = data.validated_data["start_time"]
                duration_hours = data.validated_data["duration_hours"]
                start_minute = minutes_after_midnight(start_time)
                opening_minute, closing_minute = venue_hours(venue)
                duration_minutes = int(duration_hours * 60)
                if (
                    start_minute < opening_minute
                    or start_minute + duration_minutes > closing_minute
                    or (start_minute - opening_minute) % duration_minutes
                ):
                    raise ValidationError(
                        "Choose a session start aligned to the selected duration within this venue's opening hours."
                    )
                bookings = list(
                    Booking.objects.filter(
                        venue=venue,
                        game_date=game_date,
                        status__in=ACTIVE_BOOKING_STATUSES,
                    ).values_list("player_id", "start_time", "duration_minutes")
                )
                intervals = [
                    (booked_start.hour * 60 + booked_start.minute, duration)
                    for _, booked_start, duration in bookings
                ]
                player_intervals = [
                    (booked_start.hour * 60 + booked_start.minute, duration)
                    for player_id, booked_start, duration in bookings
                    if player_id == request.user.pk
                ]
                end_minute = start_minute + duration_minutes
                if any(
                    booked_start < end_minute
                    and booked_start + duration > start_minute
                    for booked_start, duration in player_intervals
                ):
                    raise ValidationError("You already have a booking overlapping that time.")
                if not available_systems(venue, intervals, start_minute, duration_minutes):
                    raise ValidationError("Those hours are no longer available.")
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
        except IntegrityError as error:
            raise ValidationError("You already have a booking starting at that time.") from error
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


class PlayerBookingsView(APIView):
    permission_classes = [IsAuthenticated, IsPlayer]

    @extend_schema(responses=BookingSerializer(many=True), tags=["Player bookings"])
    def get(self, request):
        bookings = Booking.objects.filter(player=request.user).select_related("venue")
        return Response(BookingSerializer(bookings, many=True).data)


class VendorVenuesView(APIView):
    permission_classes = [IsAuthenticated, IsVendor]

    @extend_schema(responses=VenueSerializer(many=True), tags=["Vendor venues"])
    def get(self, request):
        venues = Venue.objects.filter(owner=request.user)
        return Response(VenueSerializer(venues, many=True).data)

    @extend_schema(request=VenueSerializer, responses={201: VenueSerializer}, tags=["Vendor venues"])
    def post(self, request):
        serializer = VenueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        venue = serializer.save(owner=request.user)
        return Response(VenueSerializer(venue).data, status=status.HTTP_201_CREATED)


class VendorVenueDetailView(APIView):
    permission_classes = [IsAuthenticated, IsVendor]

    @extend_schema(responses=VenueSerializer, tags=["Vendor venues"])
    def get(self, request, venue_id):
        venue = get_object_or_404(Venue, pk=venue_id, owner=request.user)
        return Response(VenueSerializer(venue).data)

    @extend_schema(request=VenueSerializer, responses=VenueSerializer, tags=["Vendor venues"])
    def patch(self, request, venue_id):
        venue = get_object_or_404(Venue, pk=venue_id, owner=request.user)
        serializer = VenueSerializer(venue, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class VendorBookingsView(APIView):
    permission_classes = [IsAuthenticated, IsVendor]

    @extend_schema(
        parameters=[
            OpenApiParameter("status", str, description="Optional booking status filter."),
            OpenApiParameter("date", str, description="Optional ISO date filter (YYYY-MM-DD)."),
        ],
        responses=BookingSerializer(many=True),
        tags=["Vendor bookings"],
    )
    def get(self, request):
        bookings = Booking.objects.filter(venue__owner=request.user).select_related(
            "venue",
            "player",
        )
        booking_status = request.query_params.get("status")
        game_date = request.query_params.get("date")
        if booking_status:
            bookings = bookings.filter(status=booking_status)
        if game_date:
            bookings = bookings.filter(game_date=game_date)
        return Response(BookingSerializer(bookings, many=True).data)


class VendorBookingActionView(APIView):
    permission_classes = [IsAuthenticated, IsVendor]
    action_status = None

    def _update_booking(self, request, booking_id):
        with transaction.atomic():
            booking = get_object_or_404(
                Booking.objects.select_for_update().select_related("venue"),
                pk=booking_id,
                venue__owner=request.user,
            )
            if booking.status != Booking.Status.PENDING:
                raise ValidationError("Only pending bookings can be accepted or released.")
            booking.status = self.action_status
            booking.save(update_fields=["status"])
        return Response(BookingSerializer(booking).data)

    @extend_schema(request=None, responses=BookingSerializer, tags=["Vendor bookings"])
    def post(self, request, booking_id):
        return self._update_booking(request, booking_id)


class AcceptBookingView(VendorBookingActionView):
    action_status = Booking.Status.CONFIRMED


class ReleaseBookingView(VendorBookingActionView):
    action_status = Booking.Status.CANCELLED
