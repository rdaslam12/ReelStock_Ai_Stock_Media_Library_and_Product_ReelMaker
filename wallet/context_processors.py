"""
Context processor exposing wallet info to every template.

Without this, the navbar would have to query the DB inside the template
for every request — uglier and easy to forget. Adding this once means
every page automatically has `wallet_balance`, `basket_count`, and
`basket_item_ids` available.
"""
from .models import BasketItem, Wallet


def wallet_context(request):
    if not request.user.is_authenticated:
        return {
            'wallet_balance': 0,
            'basket_count': 0,
            'basket_image_ids': set(),
            'basket_video_ids': set(),
        }

    # Get-or-create so existing pre-feature accounts don't crash.
    wallet, created = Wallet.objects.get_or_create(
        user=request.user, defaults={'balance': Wallet.SIGNUP_BONUS},
    )
    if created:
        # Mirror the signup bonus in the audit log.
        from .models import Transaction
        Transaction.objects.create(
            wallet=wallet,
            kind=Transaction.KIND_SIGNUP,
            delta=Wallet.SIGNUP_BONUS,
            balance_after=wallet.balance,
            note="Welcome bonus (back-filled).",
        )

    items = BasketItem.objects.filter(user=request.user).only('image_id', 'video_id')
    image_ids = {i.image_id for i in items if i.image_id}
    video_ids = {i.video_id for i in items if i.video_id}

    return {
        'wallet_balance': wallet.balance,
        'basket_count': len(image_ids) + len(video_ids),
        'basket_image_ids': image_ids,
        'basket_video_ids': video_ids,
    }
