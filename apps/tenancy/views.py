from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from .models import Organization, Membership
from .serializers import OrganizationSerializer
from .middleware import resolve_org


class OrganizationListCreateView(generics.ListCreateAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        return (
            Organization.objects
            .filter(memberships__user=self.request.user, deleted_at__isnull=True)
            .distinct()
            .order_by("created_at")
        )

    def perform_create(self, serializer):
        org = serializer.save()
        Membership.objects.create(org=org, user=self.request.user, role=Membership.Role.OWNER)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(
            {"success": True, "data": serializer.data},
            status=status.HTTP_201_CREATED,
        )

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        serializer = self.get_serializer(qs, many=True)
        return Response({
            "success": True,
            "count": qs.count(),
            "results": serializer.data,
        })


class OrganizationDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = OrganizationSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["request"] = self.request
        return ctx

    def get_queryset(self):
        # Strict: user must be a member AND org must not be soft-deleted
        return Organization.objects.filter(
            memberships__user=self.request.user,
            deleted_at__isnull=True,
        )

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        return Response({"success": True, "data": serializer.data})

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        # Only owner/admin may update
        membership = Membership.objects.filter(org=instance, user=request.user).first()
        if not membership or membership.role not in (Membership.Role.OWNER, Membership.Role.ADMIN):
            return Response(
                {"success": False, "message": "Only owners and admins can update the organisation."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"success": True, "data": serializer.data})

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        # Only the owner can delete
        membership = Membership.objects.filter(org=instance, user=request.user).first()
        if not membership or membership.role != Membership.Role.OWNER:
            return Response(
                {"success": False, "message": "Only the owner can delete the organisation."},
                status=status.HTTP_403_FORBIDDEN,
            )
        instance.deleted_at = timezone.now()
        instance.save(update_fields=["deleted_at"])
        return Response({"success": True, "message": "Organisation deleted."}, status=status.HTTP_200_OK)


class SwitchOrgView(APIView):
    """
    POST /api/v1/organizations/<pk>/switch

    Validates membership and returns org details + role so the frontend
    can store the new cn_org_id and update its AppUser.org state.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            membership = Membership.objects.select_related("org").get(
                org_id=pk,
                user=request.user,
                org__deleted_at__isnull=True,
            )
        except Membership.DoesNotExist:
            return Response(
                {"success": False, "message": "Organisation not found or you are not a member.", "code": "NOT_FOUND"},
                status=404,
            )
        org = membership.org
        serializer = OrganizationSerializer(org, context={"request": request})
        return Response({
            "success": True,
            "data": {
                **serializer.data,
                "role": membership.role,
            },
        })


class OrgMembersView(APIView):
    """
    GET /api/v1/organizations/<pk>/members — list members of an org.
    Only members of the org can view.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            Membership.objects.get(org_id=pk, user=request.user)
        except Membership.DoesNotExist:
            return Response({"success": False, "message": "Not found."}, status=404)

        members = Membership.objects.filter(org_id=pk).select_related("user").order_by("created_at")
        return Response({
            "success": True,
            "results": [
                {
                    "id": str(m.user.id),
                    "name": m.user.name,
                    "email": m.user.email,
                    "role": m.role,
                    "joined_at": m.created_at,
                }
                for m in members
            ],
        })


class HealthView(APIView):
    permission_classes = []
    authentication_classes = []

    def get(self, request):
        return Response({
            "success": True,
            "data": {"status": "ok", "service": "collectnaija-api", "version": "1.0.0"},
        })
