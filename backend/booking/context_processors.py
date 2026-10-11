from .models import Booking


def vendor_notifications(request):
    pending_count = 0
    if (
        request.user.is_authenticated
        and request.user.role == request.user.Role.VENDOR
    ):
        pending_count = Booking.objects.filter(
            venue__owner=request.user,
            status=Booking.Status.PENDING,
        ).count()
    return {"vendor_pending_count": pending_count}
