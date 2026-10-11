from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from django.db.models import Q

from .models import MAX_VENUE_IMAGE_SIZE, ActivityCategory, User, Venue


class PlayerSignUpForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class VendorSignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")


class PlayerAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role != User.Role.PLAYER:
            raise ValidationError("Use the vendor portal to log in to a vendor account.")


class VendorAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role != User.Role.VENDOR:
            raise ValidationError("This login is for vendor accounts.")


class VenueForm(forms.ModelForm):
    address_line = forms.CharField(
        max_length=255,
        label="Complete address line",
        help_text="Street, building, and unit or landmark.",
    )
    city = forms.CharField(max_length=100)
    state = forms.CharField(max_length=100)
    country = forms.CharField(max_length=100)
    category = forms.ChoiceField(choices=())

    class Meta:
        model = Venue
        fields = (
            "name",
            "address_line",
            "city",
            "state",
            "country",
            "postal_code",
            "category",
            "photo",
            "description",
            "hourly_rate",
            "system_count",
            "opening_time",
            "closing_time",
        )
        labels = {
            "city": "City",
            "state": "State / province",
            "country": "Country",
            "postal_code": "PIN code / postal code",
            "system_count": "Bookable units available",
            "opening_time": "Opens at",
            "closing_time": "Closes at",
        }
        help_texts = {
            "photo": "Optional. Upload a JPG, PNG, GIF, or WebP image up to 5 MB.",
            "postal_code": "Enter the venue's postal code so nearby players can find it.",
            "system_count": "Total tables, systems, courts, or other units available to book.",
            "opening_time": "Daily opening time. Session start times are generated automatically.",
            "closing_time": "Daily closing time. Choose 12:00 AM to close at midnight.",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "opening_time": forms.TimeInput(attrs={"type": "time"}),
            "closing_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        categories = ActivityCategory.objects.filter(is_active=True)
        if self.instance.pk and self.instance.category:
            categories = ActivityCategory.objects.filter(
                Q(is_active=True) | Q(slug=self.instance.category)
            )
        self.fields["category"].choices = [
            (category.slug, category.name)
            for category in categories
        ]

    def save(self, commit=True):
        venue = super().save(commit=False)
        venue.location = venue.city
        if commit:
            venue.save()
            self.save_m2m()
        return venue

    def clean(self):
        cleaned_data = super().clean()
        uploaded_photo = self.files.get("photo")
        if uploaded_photo and uploaded_photo.size > MAX_VENUE_IMAGE_SIZE:
            self.add_error("photo", "Venue images must be 5 MB or smaller.")
        opening_time = cleaned_data.get("opening_time")
        closing_time = cleaned_data.get("closing_time")
        if opening_time and closing_time:
            if opening_time.minute not in (0, 30) or opening_time.second:
                self.add_error(
                    "opening_time",
                    "Opening time must be on the hour or half hour.",
                )
            close_minute = (
                closing_time.hour * 60 + closing_time.minute
                if closing_time.hour or closing_time.minute
                else 24 * 60
            )
            if closing_time.second:
                self.add_error("closing_time", "Closing time must be set to the minute.")
            if close_minute <= opening_time.hour * 60 + opening_time.minute:
                self.add_error("closing_time", "Closing time must be after opening time.")
            elif self.instance.pk and (
                opening_time != self.instance.opening_time
                or closing_time != self.instance.closing_time
            ):
                active_bookings = self.instance.bookings.filter(
                    status__in=("pending", "confirmed"),
                )
                if any(
                    booking.start_time < opening_time
                    or (
                        booking.start_time.hour * 60
                        + booking.start_time.minute
                        + booking.duration_minutes
                        > close_minute
                    )
                    for booking in active_bookings
                ):
                    self.add_error(
                        "closing_time",
                        "Hours cannot change to exclude an active booking.",
                    )
        return cleaned_data
