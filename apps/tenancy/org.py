"""
Canonical org resolution for views and serializers.

Why this exists
---------------
`CurrentOrgMiddleware` runs BEFORE DRF authenticates the request, so for JWT
requests `request.org` is always None at that point. Any view that reads
`getattr(request, "org", None)` therefore gets None and silently returns an
empty queryset — records exist in the database but the API reports none.

Customers/invoices worked only because they each grew a private `_get_org()`
helper with a `user.memberships` fallback. This module is that fallback, in one
place, so every app resolves the org the same way.

Usage
-----
    from apps.tenancy.org import get_org

    def get_queryset(self):
        org = get_org(self.request)
        if org is None:
            return Model.objects.none()
        return Model.objects.for_org(org)
"""

__all__ = ["get_org", "require_org"]


def get_org(request):
    """Return the active Organization for this request, or None.

    Honours the X-Org-Id header (validated against the user's memberships),
    otherwise falls back to the user's first active membership.
    """
    if request is None:
        return None

    # Already resolved (session auth, or an earlier call in this request).
    org = getattr(request, "org", None)
    if org is not None:
        return org

    # Accessing .user on a DRF Request triggers authentication, so this is
    # safe to do here even though the middleware could not do it earlier.
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    from .middleware import _resolve_org_for_user

    headers = getattr(request, "headers", None) or {}
    org = _resolve_org_for_user(user, headers)

    # Cache so repeat lookups in the same request are free. Only cache a hit;
    # caching None would mask a membership created mid-request.
    if org is not None:
        try:
            request.org = org
        except AttributeError:
            pass

    return org


def require_org(request):
    """Like get_org, but raises instead of returning None.

    Use in write paths (POST/PATCH) where a missing org means the request is
    malformed — returning 404 beats writing a row with org_id NULL, which
    fails as an IntegrityError (HTTP 500) deep in the database layer.
    """
    from rest_framework.exceptions import NotFound

    org = get_org(request)
    if org is None:
        raise NotFound("Organization context required.")
    return org
