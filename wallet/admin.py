"""
Django admin configuration for wallet & basket models.

Highlight: CoinRequest can be Approved or Rejected with a single click via
admin actions. Approving automatically credits the user's wallet AND records
a Transaction in the audit log — no manual coin manipulation required.
"""
from django.contrib import admin, messages
from django.utils import timezone

from .models import BasketItem, CoinRequest, Transaction, Wallet


def _wallet_for_user(user):
    """Return a wallet for any user, including accounts created before wallet support."""
    wallet, created = Wallet.objects.get_or_create(
        user=user,
        defaults={'balance': Wallet.SIGNUP_BONUS},
    )
    if created:
        Transaction.objects.create(
            wallet=wallet,
            kind=Transaction.KIND_SIGNUP,
            delta=Wallet.SIGNUP_BONUS,
            balance_after=wallet.balance,
            note="Welcome bonus (back-filled from admin).",
        )
    return wallet


# ─────────────────────────────────────────────────────────────────────────────
@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display  = ['user', 'balance', 'updated_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    list_filter   = ['created_at']
    ordering      = ['-balance']


# ─────────────────────────────────────────────────────────────────────────────
@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'wallet', 'kind', 'delta', 'balance_after', 'note']
    list_filter  = ['kind', 'created_at']
    search_fields = ['wallet__user__username', 'note']
    readonly_fields = ['created_at']
    date_hierarchy = 'created_at'


# ─────────────────────────────────────────────────────────────────────────────
@admin.register(CoinRequest)
class CoinRequestAdmin(admin.ModelAdmin):
    """
    Admin can approve or reject a CoinRequest with a single click.
    Approving instantly credits the user's wallet.
    """
    list_display  = ['created_at', 'user', 'amount', 'usd_amount', 'payment_method', 'transaction_id', 'status', 'admin_note']
    list_filter   = ['status', 'payment_method', 'created_at']
    search_fields = ['user__username', 'user__email', 'reason', 'transaction_id']
    readonly_fields = ['created_at', 'resolved_at', 'resolved_by']
    actions = ['approve_requests', 'reject_requests']

    fieldsets = (
        ('Request', {
            'fields': ('user', 'amount', 'usd_amount', 'payment_method', 'transaction_id', 'reason', 'created_at'),
        }),
        ('Decision', {
            'fields': ('status', 'admin_note', 'resolved_at', 'resolved_by'),
        }),
    )

    @admin.action(description='✅ Approve selected requests (credits wallet)')
    def approve_requests(self, request, queryset):
        approved = 0
        for cr in queryset.filter(status=CoinRequest.STATUS_PENDING):
            wallet = _wallet_for_user(cr.user)
            wallet.credit(
                cr.amount,
                kind=Transaction.KIND_GRANT,
                note=f"Coin request #{cr.pk} approved by {request.user.username}",
            )
            cr.status = CoinRequest.STATUS_APPROVED
            cr.resolved_at = timezone.now()
            cr.resolved_by = request.user
            if not cr.admin_note:
                cr.admin_note = f"Approved by {request.user.username}"
            cr.save()
            approved += 1
        self.message_user(
            request,
            f"Approved {approved} request(s) and credited the wallets.",
            level=messages.SUCCESS,
        )

    @admin.action(description='❌ Reject selected requests')
    def reject_requests(self, request, queryset):
        rejected = queryset.filter(status=CoinRequest.STATUS_PENDING).update(
            status=CoinRequest.STATUS_REJECTED,
            resolved_at=timezone.now(),
            resolved_by=request.user,
            admin_note=f"Rejected by {request.user.username}",
        )
        self.message_user(
            request,
            f"Rejected {rejected} request(s).",
            level=messages.WARNING,
        )

    def save_model(self, request, obj, form, change):
        """
        If the admin manually flips status from Pending → Approved in the form
        (rather than using the bulk action), we still need to credit the wallet.
        """
        if change and obj.pk:
            old = CoinRequest.objects.get(pk=obj.pk)
            became_approved = (
                old.status == CoinRequest.STATUS_PENDING
                and obj.status == CoinRequest.STATUS_APPROVED
            )
            if became_approved:
                wallet = _wallet_for_user(obj.user)
                wallet.credit(
                    obj.amount,
                    kind=Transaction.KIND_GRANT,
                    note=f"Coin request #{obj.pk} approved by {request.user.username}",
                )
                obj.resolved_at = timezone.now()
                obj.resolved_by = request.user
                if not obj.admin_note:
                    obj.admin_note = f"Approved by {request.user.username}"
            elif (
                old.status == CoinRequest.STATUS_PENDING
                and obj.status == CoinRequest.STATUS_REJECTED
            ):
                obj.resolved_at = timezone.now()
                obj.resolved_by = request.user
                if not obj.admin_note:
                    obj.admin_note = f"Rejected by {request.user.username}"
        super().save_model(request, obj, form, change)


# ─────────────────────────────────────────────────────────────────────────────
@admin.register(BasketItem)
class BasketItemAdmin(admin.ModelAdmin):
    list_display = ['user', 'asset_label', 'coin_price_snapshot', 'added_at']
    list_filter  = ['added_at']
    search_fields = ['user__username']
    readonly_fields = ['added_at']

    def asset_label(self, obj):
        return obj.title
    asset_label.short_description = 'Asset'
