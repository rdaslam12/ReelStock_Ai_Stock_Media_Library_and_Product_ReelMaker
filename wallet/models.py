"""
Wallet & Download Basket models.

Concept
-------
ReelStock uses an in-app virtual currency called "Reel Coins" (RC).
- Every user has exactly one Wallet with a coin balance.
- New users start with 100 RC (welcome bonus).
- Library assets (images / videos) have a fixed coin price.
- Users add items to their Download Basket (server-side, persists across pages).
- When they "Confirm Download", coins are deducted, a Transaction is recorded,
  and the chosen assets are bundled into a ZIP file.
- If the balance is insufficient, the user can submit a CoinRequest. An admin
  approves or rejects it from the Django admin panel.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import User
from django.db import models


# ─────────────────────────────────────────────────────────────────────────────
#  Wallet
# ─────────────────────────────────────────────────────────────────────────────
class Wallet(models.Model):
    """One-to-one with User. Stores the current Reel Coin balance."""
    SIGNUP_BONUS = 100  # Coins given on registration

    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='wallet',
    )
    balance = models.PositiveIntegerField(default=SIGNUP_BONUS)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Wallet'
        verbose_name_plural = 'Wallets'

    def __str__(self):
        return f"{self.user.username} • {self.balance} RC"

    # ── Helpers ────────────────────────────────────────────────────────────
    def credit(self, amount: int, kind: str, note: str = ''):
        """Add coins and record a transaction. Returns the Transaction."""
        amount = int(amount)
        if amount <= 0:
            raise ValueError("Credit amount must be positive.")
        self.balance += amount
        self.save(update_fields=['balance', 'updated_at'])
        return Transaction.objects.create(
            wallet=self, kind=kind, delta=amount, note=note,
            balance_after=self.balance,
        )

    def debit(self, amount: int, kind: str, note: str = ''):
        """Spend coins. Raises ValueError if balance is too low."""
        amount = int(amount)
        if amount <= 0:
            raise ValueError("Debit amount must be positive.")
        if amount > self.balance:
            raise ValueError("Insufficient balance.")
        self.balance -= amount
        self.save(update_fields=['balance', 'updated_at'])
        return Transaction.objects.create(
            wallet=self, kind=kind, delta=-amount, note=note,
            balance_after=self.balance,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  Transaction
# ─────────────────────────────────────────────────────────────────────────────
class Transaction(models.Model):
    """Audit log of every coin movement."""

    KIND_SIGNUP   = 'signup_bonus'
    KIND_DOWNLOAD = 'download'
    KIND_GRANT    = 'admin_grant'
    KIND_ADJUST   = 'admin_adjust'
    KIND_CHOICES = [
        (KIND_SIGNUP,   'Welcome Bonus'),
        (KIND_DOWNLOAD, 'Download Purchase'),
        (KIND_GRANT,    'Coin Request Approved'),
        (KIND_ADJUST,   'Manual Adjustment'),
    ]

    wallet  = models.ForeignKey(
        Wallet, on_delete=models.CASCADE, related_name='transactions',
    )
    kind    = models.CharField(max_length=24, choices=KIND_CHOICES)
    delta   = models.IntegerField(help_text="Positive = credit, negative = debit.")
    balance_after = models.PositiveIntegerField()
    note    = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        sign = '+' if self.delta >= 0 else ''
        return f"{self.wallet.user.username} {sign}{self.delta} RC ({self.get_kind_display()})"


# ─────────────────────────────────────────────────────────────────────────────
#  CoinRequest  (user → admin approval flow)
# ─────────────────────────────────────────────────────────────────────────────
class CoinRequest(models.Model):
    """A user-submitted request for more coins. Admin approves/rejects in /admin/."""

    STATUS_PENDING  = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_PENDING,  'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    PAYMENT_PAYPAL     = 'paypal'
    PAYMENT_APPLEPAY   = 'applepay'
    PAYMENT_GOOGLEPAY  = 'googlepay'
    PAYMENT_CHOICES = [
        (PAYMENT_PAYPAL,    'PayPal'),
        (PAYMENT_APPLEPAY,  'Apple Pay'),
        (PAYMENT_GOOGLEPAY, 'Google Pay'),
    ]

    user      = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='coin_requests',
    )
    amount    = models.PositiveIntegerField()
    reason    = models.TextField(blank=True)
    payment_method = models.CharField(
        max_length=16, choices=PAYMENT_CHOICES, default=PAYMENT_PAYPAL,
        verbose_name='Payment Method',
    )
    transaction_id = models.CharField(
        max_length=100, blank=True, verbose_name='Transaction ID',
        help_text='Payment transaction or confirmation reference provided by the user.',
    )
    usd_amount = models.DecimalField(
        max_digits=8, decimal_places=2, default=0,
        verbose_name='USD Amount Paid',
    )
    status    = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_PENDING)
    admin_note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='resolved_coin_requests',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} → {self.amount} RC [{self.get_status_display()}]"


# ─────────────────────────────────────────────────────────────────────────────
#  BasketItem  (Download Basket — persists in DB, survives refresh)
# ─────────────────────────────────────────────────────────────────────────────
class BasketItem(models.Model):
    """One item in a user's Download Basket. Links to either an image or a video."""

    user  = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='basket_items',
    )
    image = models.ForeignKey(
        'core.GeneratedImage', null=True, blank=True,
        on_delete=models.CASCADE, related_name='+',
    )
    video = models.ForeignKey(
        'core.GeneratedVideo', null=True, blank=True,
        on_delete=models.CASCADE, related_name='+',
    )
    # Snapshot the price at add-time so the cart total is stable
    # even if an admin later changes the asset's coin_price.
    coin_price_snapshot = models.PositiveIntegerField(default=0)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            # Prevent duplicates of the same asset for one user.
            models.UniqueConstraint(
                fields=['user', 'image'],
                condition=models.Q(image__isnull=False),
                name='unique_user_image_in_basket',
            ),
            models.UniqueConstraint(
                fields=['user', 'video'],
                condition=models.Q(video__isnull=False),
                name='unique_user_video_in_basket',
            ),
        ]

    # ── Display helpers ────────────────────────────────────────────────────
    @property
    def asset(self):
        return self.image or self.video

    @property
    def asset_type(self) -> str:
        return 'image' if self.image_id else 'video'

    @property
    def title(self) -> str:
        a = self.asset
        return a.display_title() if a else 'Unknown asset'

    @property
    def thumb_url(self) -> str:
        """Best-effort thumbnail for the basket UI."""
        if self.image_id:
            return self.image.media_url or ''
        if self.video_id:
            return self.video.source_media_url or self.video.playback_url or ''
        return ''

    @property
    def media_url(self) -> str:
        """The downloadable file URL."""
        if self.image_id:
            return self.image.media_url
        if self.video_id:
            return self.video.playback_url or self.video.source_media_url
        return ''

    def __str__(self):
        return f"{self.user.username} · {self.title} ({self.coin_price_snapshot} RC)"
