import threading
_thread_locals = threading.local()


def get_current_org():
    return getattr(_thread_locals, "org", None)


def set_current_org(org):
    _thread_locals.org = org


def _resolve_org_for_user(user, headers):
    """Resolve the active org for a user given request headers."""
    if not user or not user.is_authenticated:
        return None
    org_id = None
    if headers is not None:
        org_id = headers.get("X-Org-Id") or headers.get("X-Organization-Id")
        if not org_id:
            # case-insensitive fallback for non-standard clients
            for k, v in headers.items():
                if k.lower() == "x-org-id":
                    org_id = v
                    break
    if org_id:
        from .models import Organization
        try:
            return Organization.objects.select_related().get(
                id=org_id,
                memberships__user=user,
                deleted_at__isnull=True,
            )
        except Exception:
            return None
    # No header — fall back to the user's first active membership
    m = user.memberships.select_related("org").filter(
        org__deleted_at__isnull=True
    ).order_by("created_at").first()
    return m.org if m else None


class _LazyOrg:
    """
    Descriptor that resolves request.org lazily AFTER DRF JWT auth has run.
    DRF authenticates the user on first access to `request.user`, so reading
    `request.org` from inside a view (post-auth) returns the correct value.
    The middleware sets this descriptor on the request object.
    """

    def __init__(self, raw_request, headers):
        self._request = raw_request
        self._headers = headers
        self._resolved = False
        self._org = None

    def resolve(self):
        if not self._resolved:
            # At this point DRF has already authenticated the user
            user = getattr(self._request, "user", None)
            # DRF wraps the Django request; user may live on .user or ._request.user
            if user is None or not getattr(user, "is_authenticated", False):
                try:
                    # Access via DRF's wrapped request if available
                    user = self._request._request.user  # type: ignore[attr-defined]
                except Exception:
                    pass
            self._org = _resolve_org_for_user(user, self._headers)
            self._resolved = True
        return self._org


class CurrentOrgMiddleware:
    """
    Attaches `request.org` to every Django/DRF request.

    JWT timing fix: DRF authenticates lazily (on first access to request.user),
    which happens AFTER this middleware runs. We store a lazy resolver on the
    request so views always get the correct org regardless of auth backend.

    Views that call `getattr(request, "org", None)` get the resolved org
    transparently because we attach the _LazyOrg resolver and patch __getattr__
    via a simple attribute on the DRF Request wrapper.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Attach a lazy resolver. Views read `request.org` which triggers resolution
        # after DRF has authenticated the user.
        lazy = _LazyOrg(request, request.headers)

        # Eagerly resolve for plain Django views (user already set by session/basic auth)
        if hasattr(request, "user") and getattr(request.user, "is_authenticated", False):
            org = _resolve_org_for_user(request.user, request.headers)
            request.org = org
            set_current_org(org)
        else:
            # For JWT requests: set a sentinel; views will fall back via their own
            # _get_org() helpers which read user.memberships directly.
            request.org = None
            # Store the lazy resolver so DRF views can call it
            request._org_lazy = lazy

        response = self.get_response(request)
        set_current_org(None)
        return response


def resolve_org(request):
    """
    Helper for use inside DRF views/serializers to get the active org.
    Works correctly for both session-auth and JWT because it reads
    request.user AFTER DRF authentication has run.

    Thin wrapper around apps.tenancy.org.get_org so there is a single
    implementation of the JWT fallback.

    Usage:
        org = resolve_org(request)
    """
    from .org import get_org

    org = get_org(request)
    if org is not None:
        set_current_org(org)
    return org
