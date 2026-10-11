from rest_framework.permissions import BasePermission

from .models import User


class IsPlayer(BasePermission):
    message = "This endpoint is for player accounts."

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.role == User.Role.PLAYER)


class IsVendor(BasePermission):
    message = "This endpoint is for vendor accounts."

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.role == User.Role.VENDOR)
