from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.db.models import Q

from .models import (
    ActivityCategory,
    Booking,
    User,
    Venue,
    VenueFavorite,
    VenueLike,
    VenueVisit,
)


class VenueAdminForm(forms.ModelForm):
    category = forms.ChoiceField(choices=())

    class Meta:
        model = Venue
        fields = "__all__"

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


@admin.register(User)
class NoobOGUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("NoobOG", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_staff")
    list_filter = ("role", "is_staff")


admin.site.site_header = "NoobOG administration"
admin.site.site_title = "NoobOG admin"
admin.site.index_title = "Manage NoobOG"


@admin.register(ActivityCategory)
class ActivityCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "resource_label", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "resource_label")
    prepopulated_fields = {"slug": ("name",)}

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    form = VenueAdminForm
    list_display = (
        "name",
        "owner",
        "city",
        "state",
        "country",
        "postal_code",
        "category",
        "hourly_rate",
        "opening_time",
        "closing_time",
        "system_count",
        "is_active",
    )
    list_filter = ("category", "is_active")
    search_fields = (
        "name",
        "address_line",
        "city",
        "state",
        "country",
        "postal_code",
        "owner__username",
    )


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("player", "venue", "game_date", "start_time", "duration_minutes", "status")
    list_filter = ("status", "game_date")


@admin.register(VenueFavorite)
class VenueFavoriteAdmin(admin.ModelAdmin):
    list_display = ("player", "venue", "created_at")
    search_fields = ("player__username", "venue__name")


@admin.register(VenueLike)
class VenueLikeAdmin(admin.ModelAdmin):
    list_display = ("player", "venue", "created_at")
    search_fields = ("player__username", "venue__name")


@admin.register(VenueVisit)
class VenueVisitAdmin(admin.ModelAdmin):
    list_display = ("player", "venue", "visited_at")
    search_fields = ("player__username", "venue__name")
