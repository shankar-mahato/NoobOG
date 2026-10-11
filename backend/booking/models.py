from datetime import time

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


MAX_VENUE_IMAGE_SIZE = 5 * 1024 * 1024


def validate_venue_image_size(image):
    if image.size > MAX_VENUE_IMAGE_SIZE:
        raise ValidationError("Venue images must be 5 MB or smaller.")


class User(AbstractUser):
    class Role(models.TextChoices):
        PLAYER = "player", "Player"
        VENDOR = "vendor", "Vendor"

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.PLAYER)
    profile_picture = models.ImageField(blank=True, upload_to="profile-pictures/")


class ActivityCategory(models.Model):
    slug = models.SlugField(max_length=16, unique=True)
    name = models.CharField(max_length=64)
    resource_label = models.CharField(max_length=64, default="Bookable unit")
    icon = models.CharField(max_length=8, default="✳")
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name = "activity category"
        verbose_name_plural = "activity categories"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        previous_slug = None
        if self.pk:
            previous_slug = ActivityCategory.objects.filter(
                pk=self.pk,
            ).values_list("slug", flat=True).first()
        if (
            previous_slug
            and previous_slug != self.slug
            and Venue.objects.filter(category=previous_slug).exists()
        ):
            raise ValidationError(
                {"slug": "The slug cannot change while venues use this category."}
            )


class Venue(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="venues")
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=160)
    address_line = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=12, blank=True)
    category = models.CharField(max_length=16)
    photo = models.ImageField(
        blank=True,
        upload_to="venue-images/",
        validators=[validate_venue_image_size],
    )
    description = models.TextField(blank=True)
    hourly_rate = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    opening_time = models.TimeField(default=time(10, 0))
    closing_time = models.TimeField(default=time(20, 0))
    system_count = models.PositiveSmallIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def display_address(self):
        if not any((self.address_line, self.city, self.state, self.country)):
            return ", ".join(value for value in (self.location, self.postal_code) if value)
        locality = ", ".join(value for value in (self.city, self.state) if value)
        parts = [
            self.address_line,
            locality,
            self.postal_code,
            self.country,
        ]
        address = ", ".join(value for value in parts if value)
        return address or self.location

    @property
    def activity_category(self):
        return ActivityCategory.objects.filter(slug=self.category).first()

    def get_category_display(self):
        category = self.activity_category
        return category.name if category else self.category

    @property
    def category_icon(self):
        category = self.activity_category
        return category.icon if category else "✳"

    def clean(self):
        super().clean()
        if self.opening_time and self.closing_time:
            if self.opening_time.minute not in (0, 30) or self.opening_time.second:
                raise ValidationError(
                    {"opening_time": "Opening time must be on the hour or half hour."}
                )
            if self.closing_time.second:
                raise ValidationError(
                    {"closing_time": "Closing time must be set to the minute."}
                )
            if self.closing_time != time(0, 0) and self.closing_time <= self.opening_time:
                raise ValidationError(
                    {"closing_time": "Closing time must be after opening time. Use 12:00 AM for midnight."}
                )


class VenueFavorite(models.Model):
    player = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="venue_favorites",
    )
    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="favorites",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "venue"],
                name="unique_player_venue_favorite",
            ),
        ]


class VenueLike(models.Model):
    player = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="venue_likes",
    )
    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="likes",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "venue"],
                name="unique_player_venue_like",
            ),
        ]


class VenueVisit(models.Model):
    player = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="venue_visits",
    )
    venue = models.ForeignKey(
        Venue,
        on_delete=models.CASCADE,
        related_name="visits",
    )
    visited_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-visited_at"]


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Awaiting vendor approval"
        CONFIRMED = "confirmed", "Confirmed"
        CANCELLED = "cancelled", "Cancelled"

    player = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bookings")
    venue = models.ForeignKey(Venue, on_delete=models.CASCADE, related_name="bookings")
    game_date = models.DateField()
    start_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=60)
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING,
    )
    booked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-booked_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "venue", "game_date", "start_time"],
                condition=models.Q(status__in=["pending", "confirmed"]),
                name="unique_active_booking_per_venue_start",
            ),
        ]

    def __str__(self):
        return f"{self.player.username} · {self.venue.name} · {self.game_date} {self.start_time:%H:%M}"

    @property
    def duration_hours(self):
        return self.duration_minutes / 60

    @property
    def duration_label(self):
        if self.duration_minutes == 90:
            return "1.5 hours"
        hours = self.duration_minutes // 60
        return f"{hours} {'hour' if hours == 1 else 'hours'}"

    @property
    def reference_code(self):
        return f"PS-{self.pk:06d}"
