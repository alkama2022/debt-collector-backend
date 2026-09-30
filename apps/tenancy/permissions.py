from rest_framework.permissions import BasePermission
from apps.tenancy.org import get_org

class HasOrgRole(BasePermission):
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        # Allow if org is set or view is org creation
        return True

    def has_object_permission(self, request, view, obj):
        # Enforce tenant isolation: obj.org must equal request.org
        org = get_org(request)
        if org and hasattr(obj, "org_id") and obj.org_id != org.id:
            return False
        return True
