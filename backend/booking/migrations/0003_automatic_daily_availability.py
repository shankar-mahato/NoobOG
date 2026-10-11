from django.core.validators import MinValueValidator
from django.db import migrations, models
from django.db.models import Max
import django.db.models.deletion


def migrate_slot_bookings(apps, schema_editor):
    Booking = apps.get_model("booking", "Booking")
    database = schema_editor.connection.alias
    for booking in Booking.objects.using(database).select_related("slot").iterator():
        slot = booking.slot
        Booking.objects.using(database).filter(pk=booking.pk).update(
            venue_id=slot.venue_id,
            game_date=slot.game_date,
            start_time=slot.start_time,
            duration_minutes=slot.duration_minutes,
        )
    Slot = apps.get_model("booking", "Slot")
    Venue = apps.get_model("booking", "Venue")
    for venue_id, system_count in (
        Slot.objects.using(database)
        .values("venue_id")
        .annotate(max_systems=Max("capacity"))
        .values_list("venue_id", "max_systems")
    ):
        Venue.objects.using(database).filter(pk=venue_id).update(
            system_count=system_count,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("booking", "0002_remove_booking_unique_confirmed_booking_per_player_slot_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="venue",
            name="system_count",
            field=models.PositiveSmallIntegerField(
                default=1,
                validators=[MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="venue",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="bookings",
                to="booking.venue",
            ),
        ),
        migrations.AddField(
            model_name="booking",
            name="game_date",
            field=models.DateField(null=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="start_time",
            field=models.TimeField(null=True),
        ),
        migrations.AddField(
            model_name="booking",
            name="duration_minutes",
            field=models.PositiveSmallIntegerField(
                default=60,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="booking",
            name="unique_active_booking_per_player_slot",
        ),
        migrations.RunPython(migrate_slot_bookings, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="booking",
            name="slot",
        ),
        migrations.DeleteModel(
            name="Slot",
        ),
        migrations.AlterField(
            model_name="booking",
            name="venue",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="bookings",
                to="booking.venue",
            ),
        ),
        migrations.AlterField(
            model_name="booking",
            name="game_date",
            field=models.DateField(),
        ),
        migrations.AlterField(
            model_name="booking",
            name="start_time",
            field=models.TimeField(),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=["pending", "confirmed"]),
                fields=("player", "venue", "game_date", "start_time"),
                name="unique_active_booking_per_venue_start",
            ),
        ),
    ]
