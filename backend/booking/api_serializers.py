from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers

from .models import ActivityCategory, Booking, User, Venue
from .services import minutes_after_midnight


class AccountRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ("id", "username", "email", "password")
        read_only_fields = ("id",)

    def validate(self, attrs):
        if self.context.get("role") == User.Role.VENDOR and not attrs.get("email"):
            raise serializers.ValidationError({"email": "Vendor accounts require an email address."})
        validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        role = self.context["role"]
        user = User.objects.create_user(**validated_data, role=role)
        return user


class LoginRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class AuthenticatedUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)
    role = serializers.ChoiceField(choices=User.Role.choices)


class TokenResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = AuthenticatedUserSerializer()


class VenueSerializer(serializers.ModelSerializer):
    category = serializers.CharField()
    category_label = serializers.CharField(source="get_category_display", read_only=True)

    class Meta:
        model = Venue
        fields = (
            "id",
            "name",
            "location",
            "address_line",
            "city",
            "state",
            "country",
            "postal_code",
            "category",
            "category_label",
            "photo",
            "description",
            "hourly_rate",
            "system_count",
            "opening_time",
            "closing_time",
            "is_active",
        )
        read_only_fields = ("id",)

    def validate_category(self, value):
        category = ActivityCategory.objects.filter(slug=value).first()
        if category is None or (
            not category.is_active
            and (self.instance is None or self.instance.category != value)
        ):
            raise serializers.ValidationError("Choose an active activity category.")
        return value

    def validate(self, attrs):
        defaults = self.instance or Venue()
        opening_time = attrs.get("opening_time", defaults.opening_time)
        closing_time = attrs.get("closing_time", defaults.closing_time)
        closing_minute = minutes_after_midnight(closing_time) or 24 * 60
        if opening_time.minute not in (0, 30) or opening_time.second:
            raise serializers.ValidationError(
                {"opening_time": "Opening time must be on the hour or half hour."}
            )
        if closing_time.second:
            raise serializers.ValidationError(
                {"closing_time": "Closing time must be set to the minute."}
            )
        if closing_minute <= minutes_after_midnight(opening_time):
            raise serializers.ValidationError(
                {"closing_time": "Closing time must be after opening time. Use 12:00 AM for midnight."}
            )
        if self.instance and (
            opening_time != self.instance.opening_time
            or closing_time != self.instance.closing_time
        ):
            active_bookings = self.instance.bookings.filter(
                status__in=(Booking.Status.PENDING, Booking.Status.CONFIRMED),
            ).values_list("start_time", "duration_minutes")
            if any(
                start_time < opening_time
                or minutes_after_midnight(start_time) + duration > closing_minute
                for start_time, duration in active_bookings
            ):
                raise serializers.ValidationError(
                    {"closing_time": "Hours cannot change to exclude an active booking."}
                )
        return attrs


class BookingSerializer(serializers.ModelSerializer):
    reference_code = serializers.CharField(read_only=True)
    venue_name = serializers.CharField(source="venue.name", read_only=True)
    venue_location = serializers.CharField(source="venue.display_address", read_only=True)
    player_username = serializers.CharField(source="player.username", read_only=True)
    duration_hours = serializers.FloatField(read_only=True)

    class Meta:
        model = Booking
        fields = (
            "id",
            "reference_code",
            "venue",
            "venue_name",
            "venue_location",
            "player_username",
            "game_date",
            "start_time",
            "duration_minutes",
            "duration_hours",
            "status",
            "booked_at",
        )
        read_only_fields = fields


class BookingRequestSerializer(serializers.Serializer):
    game_date = serializers.DateField()
    start_time = serializers.TimeField()
    duration_hours = serializers.FloatField(min_value=1)

    def validate(self, attrs):
        game_date = attrs["game_date"]
        start_time = attrs["start_time"]
        duration_hours = attrs["duration_hours"]
        if duration_hours != 1.5 and not duration_hours.is_integer():
            raise serializers.ValidationError(
                {"duration_hours": "Choose a whole-hour duration or 1.5 hours."}
            )
        if (
            game_date < timezone.localdate()
            or start_time.minute not in (0, 30)
            or start_time.second != 0
            or (game_date == timezone.localdate() and start_time <= timezone.localtime().time())
        ):
            raise serializers.ValidationError(
                "Choose a future start time on a 30-minute boundary."
            )
        return attrs


class AvailabilityQuerySerializer(serializers.Serializer):
    date = serializers.DateField(required=False)

    def validate_date(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("Choose today or a future date.")
        return value


class DurationAvailabilitySerializer(serializers.Serializer):
    hours = serializers.FloatField()
    minutes = serializers.IntegerField()
    systems_left = serializers.IntegerField()


class AvailabilitySlotSerializer(serializers.Serializer):
    start_time = serializers.TimeField()
    systems_left = serializers.IntegerField()
    durations = DurationAvailabilitySerializer(many=True)


class VenueAvailabilitySerializer(serializers.Serializer):
    venue = serializers.IntegerField()
    date = serializers.DateField()
    opening_time = serializers.CharField()
    closing_time = serializers.CharField()
    slots = AvailabilitySlotSerializer(many=True)
