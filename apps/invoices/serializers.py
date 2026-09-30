from rest_framework import serializers
from .models import Invoice, InvoiceItem
from apps.tenancy.org import get_org

class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields = ["id", "name", "qty", "unit_price_minor", "line_total"]
        read_only_fields = ["id", "line_total"]

class InvoiceSerializer(serializers.ModelSerializer):
    items = InvoiceItemSerializer(many=True, required=False)
    invoice_number = serializers.CharField(required=False, allow_blank=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default="0.00")
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default="0.00")
    tax = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default="0.00")
    total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    balance = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)

    class Meta:
        model = Invoice
        fields = ["id", "org", "customer", "invoice_number", "status", "due_date", "subtotal", "discount", "tax", "total", "balance", "currency", "sent_at", "idempotency_key", "created_at", "deleted_at", "items"]
        read_only_fields = ["id", "org", "created_at", "deleted_at"]

    def create(self, validated_data):
        from decimal import Decimal
        items_data = validated_data.pop("items", [])
        request = self.context.get("request")
        org = get_org(request) if request else None
        if org is None and request and hasattr(request, "user") and request.user.is_authenticated:
            m = request.user.memberships.select_related("org").first()
            if m:
                org = m.org
        if org is None:
            raise serializers.ValidationError({"org": "Organization context required."})
        validated_data["org"] = org
        if not validated_data.get("invoice_number"):
            import uuid as _uuid
            validated_data["invoice_number"] = f"INV-{str(_uuid.uuid4())[:8].upper()}"
        # idempotency key from header if not in payload
        if not validated_data.get("idempotency_key") and request:
            hdr = request.headers.get("X-Idempotency-Key") or request.headers.get("Idempotency-Key") or request.headers.get("X-IDEMPOTENCY-KEY")
            if hdr:
                validated_data["idempotency_key"] = hdr
        # backend is source of truth: recompute from items when items provided
        if items_data:
            calc_subtotal = sum(Decimal(str(i.get("qty", 1))) * Decimal(str(i.get("unit_price_minor", 0))) / Decimal("100") for i in items_data)
            validated_data["subtotal"] = calc_subtotal
        subtotal = validated_data.get("subtotal", Decimal("0.00"))
        discount = validated_data.get("discount", Decimal("0.00"))
        tax = validated_data.get("tax", Decimal("0.00"))
        total = Decimal(subtotal) - Decimal(discount) + Decimal(tax)
        validated_data["total"] = total
        validated_data["balance"] = total
        # balance will be reduced by payments later; on create balance == total
        # check idempotency replay
        ik = validated_data.get("idempotency_key")
        if ik:
            existing = Invoice.objects.filter(idempotency_key=ik).first()
            if existing:
                return existing
        invoice = Invoice(**validated_data)
        invoice.full_clean()
        invoice.save()
        for item_data in items_data:
            qty = Decimal(str(item_data.get("qty", 1)))
            minor = int(item_data.get("unit_price_minor", 0))
            line_total = qty * Decimal(minor) / Decimal("100")
            InvoiceItem.objects.create(invoice=invoice, name=item_data.get("name","Item"), qty=qty, unit_price_minor=minor, line_total=line_total)
        return invoice

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.full_clean()
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                InvoiceItem.objects.create(invoice=instance, **item_data)
        return instance
