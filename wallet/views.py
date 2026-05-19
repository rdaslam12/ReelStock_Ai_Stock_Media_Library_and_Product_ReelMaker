"""
Views for the Wallet & Download Basket app.

URL surface
-----------
GET   /basket/                    → Basket page (list, total, confirm button)
POST  /basket/add/                → Add an item (asset_type + asset_id in body)
POST  /basket/remove/<item_id>/   → Remove a single item
POST  /basket/clear/              → Clear the whole basket
POST  /basket/confirm/            → Pay coins, build ZIP, return as download
GET   /basket/count/              → JSON {count, balance} for the navbar badge
GET   /wallet/                    → Wallet page (balance + transaction history)
POST  /wallet/request-coins/      → Submit a CoinRequest to the admin
"""
from __future__ import annotations

import io
import json
import logging
import os
import zipfile
from decimal import Decimal
from urllib.parse import urlparse

import requests

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_POST, require_GET

from core.models import GeneratedImage, GeneratedVideo

from .models import BasketItem, CoinRequest, Transaction, Wallet

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _get_or_create_wallet(user) -> Wallet:
    """Defensive helper — if signals were ever skipped, build one on demand."""
    wallet, created = Wallet.objects.get_or_create(
        user=user, defaults={'balance': Wallet.SIGNUP_BONUS},
    )
    if created:
        Transaction.objects.create(
            wallet=wallet,
            kind=Transaction.KIND_SIGNUP,
            delta=Wallet.SIGNUP_BONUS,
            balance_after=wallet.balance,
            note="Welcome bonus.",
        )
    return wallet


def _basket_context(user) -> dict:
    items = (
        BasketItem.objects
        .filter(user=user)
        .select_related('image', 'video', 'image__user', 'video__user')
    )
    item_list = list(items)
    total_coins = sum(i.coin_price_snapshot for i in item_list)
    wallet = _get_or_create_wallet(user)
    return {
        'items': item_list,
        'item_count': len(item_list),
        'total_coins': total_coins,
        'wallet': wallet,
        'balance': wallet.balance,
        'enough_balance': wallet.balance >= total_coins,
        'coins_short': max(0, total_coins - wallet.balance),
        'remaining_after': max(0, wallet.balance - total_coins),
    }


def _resolve_local_path(media_url: str) -> str | None:
    """If media_url points to /media/..., return the local file path. Else None."""
    if not media_url:
        return None
    media_prefix = settings.MEDIA_URL  # e.g. '/media/'
    if media_url.startswith(media_prefix):
        relative = media_url[len(media_prefix):]
        return os.path.join(settings.MEDIA_ROOT, relative)
    return None


def _safe_filename(title: str, fallback: str, ext: str) -> str:
    """Build a clean filename like 'sunset_hills_42.png'."""
    slug = slugify(title)[:60] or fallback
    if not ext.startswith('.'):
        ext = '.' + ext
    return f"{slug}{ext}"


def _ext_from_url(url: str, default: str = '.bin') -> str:
    """Extract the file extension from a URL path."""
    if not url:
        return default
    path = urlparse(url).path
    _, ext = os.path.splitext(path)
    return ext if ext else default


# ─────────────────────────────────────────────────────────────────────────────
#  Basket — pages & actions
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url='/login/')
def basket_page(request):
    ctx = _basket_context(request.user)
    return render(request, 'wallet/basket.html', ctx)


@login_required(login_url='/login/')
@require_POST
def basket_add(request):
    """
    Body: { "asset_type": "image"|"video", "asset_id": 12 }
    Returns JSON { ok, in_basket, count, balance, message }
    """
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'message': 'Invalid request.'}, status=400)

    asset_type = (payload.get('asset_type') or '').strip().lower()
    asset_id   = payload.get('asset_id')

    if asset_type not in ('image', 'video') or not asset_id:
        return JsonResponse({'ok': False, 'message': 'Bad asset_type or asset_id.'}, status=400)

    if asset_type == 'image':
        asset = get_object_or_404(GeneratedImage, pk=asset_id, is_published=True)
        if asset.user_id == request.user.id:
            return JsonResponse({
                'ok': False,
                'message': "This is your own creation — you don't need to buy it. Visit My Assets to download.",
            }, status=400)
        item, created = BasketItem.objects.get_or_create(
            user=request.user, image=asset,
            defaults={'coin_price_snapshot': max(asset.coin_price, 40)},
        )
    else:
        asset = get_object_or_404(GeneratedVideo, pk=asset_id, is_published=True, status='done')
        if asset.user_id == request.user.id:
            return JsonResponse({
                'ok': False,
                'message': "This is your own creation — you don't need to buy it. Visit My Assets to download.",
            }, status=400)
        item, created = BasketItem.objects.get_or_create(
            user=request.user, video=asset,
            defaults={'coin_price_snapshot': max(asset.coin_price, 100)},
        )

    count = BasketItem.objects.filter(user=request.user).count()
    wallet = _get_or_create_wallet(request.user)

    return JsonResponse({
        'ok': True,
        'created': created,
        'in_basket': True,
        'count': count,
        'balance': wallet.balance,
        'price': item.coin_price_snapshot,
        'message': "Added to your Download Basket." if created else "Already in your basket.",
    })


@login_required(login_url='/login/')
@require_POST
def basket_remove(request, item_id: int):
    item = get_object_or_404(BasketItem, pk=item_id, user=request.user)
    item.delete()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        ctx = _basket_context(request.user)
        return JsonResponse({
            'ok': True,
            'count': ctx['item_count'],
            'total_coins': ctx['total_coins'],
            'balance': ctx['balance'],
        })
    return redirect('basket_page')


@login_required(login_url='/login/')
@require_POST
def basket_clear(request):
    BasketItem.objects.filter(user=request.user).delete()
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'count': 0, 'total_coins': 0})
    messages.success(request, "Your basket has been cleared.")
    return redirect('basket_page')


@login_required(login_url='/login/')
@require_GET
def basket_count(request):
    """Tiny endpoint used by the navbar badge to refresh after AJAX adds."""
    wallet = _get_or_create_wallet(request.user)
    count = BasketItem.objects.filter(user=request.user).count()
    return JsonResponse({'count': count, 'balance': wallet.balance})


# ─────────────────────────────────────────────────────────────────────────────
#  Confirm Download — debit coins & build a ZIP
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url='/login/')
@require_POST
def basket_confirm(request):
    """
    Atomic flow:
      1. Lock the user's wallet row.
      2. Sum up basket prices.
      3. Verify the balance covers it.
      4. Debit the wallet, log a Transaction.
      5. Stream a ZIP of every basket asset back to the browser.
      6. Empty the basket.
    """
    items = list(
        BasketItem.objects.filter(user=request.user)
        .select_related('image', 'video')
    )
    if not items:
        messages.warning(request, "Your basket is empty.")
        return redirect('basket_page')

    total = sum(i.coin_price_snapshot for i in items)

    wallet = _get_or_create_wallet(request.user)

    # Build the ZIP in memory before charging. This avoids taking coins if a
    # local file is missing or a remote asset cannot be read.
    buffer = io.BytesIO()
    seen_names: set[str] = set()
    files_written = 0
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for idx, item in enumerate(items, start=1):
            url = item.media_url
            if not url:
                continue

            ext = _ext_from_url(
                url,
                default='.png' if item.asset_type == 'image' else '.mp4',
            )
            base = _safe_filename(item.title, f"asset_{idx}", ext)
            # Make filenames unique inside the ZIP
            name = base
            n = 2
            while name in seen_names:
                stem, dot_ext = os.path.splitext(base)
                name = f"{stem}_{n}{dot_ext}"
                n += 1
            seen_names.add(name)

            data = _read_asset_bytes(url)
            if data is not None:
                zf.writestr(name, data)
                files_written += 1

        if files_written == 0:
            messages.error(
                request,
                "None of the selected files could be read, so no coins were deducted.",
            )
            return redirect('basket_page')

        zf.writestr(
            'README.txt',
            (
                "Thank you for your download from ReelStock!\n\n"
                f"User: {request.user.username}\n"
                f"Items: {files_written}\n"
                f"Coins spent: {total} RC\n"
                f"Remaining balance: {max(0, wallet.balance - total)} RC\n"
            ),
        )

    try:
        with db_transaction.atomic():
            wallet = Wallet.objects.select_for_update().get(user=request.user)
            if wallet.balance < total:
                messages.error(
                    request,
                    f"You need {total} RC but only have {wallet.balance} RC. "
                    f"Use 'Request More Coins' to top up.",
                )
                return redirect('basket_page')

            note = f"Downloaded {files_written} item{'s' if files_written != 1 else ''} as ZIP."
            wallet.debit(total, kind=Transaction.KIND_DOWNLOAD, note=note)
            BasketItem.objects.filter(user=request.user).delete()
    except Wallet.DoesNotExist:
        _get_or_create_wallet(request.user)
        messages.error(request, "Your wallet was not initialised. Please try again.")
        return redirect('basket_page')

    logger.info(
        "basket_confirm: user_id=%s files=%s charged=%s remaining=%s",
        request.user.id,
        files_written,
        total,
        wallet.balance,
    )

    # Stream back the ZIP
    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = (
        f'attachment; filename="reelstock_download_{request.user.username}.zip"'
    )
    return response


def _read_asset_bytes(url: str) -> bytes | None:
    """Fetch bytes for an asset URL — local first, then fall back to HTTP."""
    local_path = _resolve_local_path(url)
    if local_path and os.path.exists(local_path):
        try:
            with open(local_path, 'rb') as fh:
                return fh.read()
        except OSError:
            return None

    # Remote URLs (e.g. fal.ai CDN, HuggingFace). Skip if not absolute.
    if url.startswith(('http://', 'https://')):
        try:
            resp = requests.get(url, timeout=30)
            if resp.status_code == 200:
                return resp.content
        except requests.RequestException:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Wallet page  +  CoinRequest submission
# ─────────────────────────────────────────────────────────────────────────────
@login_required(login_url='/login/')
def wallet_page(request):
    wallet = _get_or_create_wallet(request.user)
    txns = wallet.transactions.all()[:50]
    coin_requests = CoinRequest.objects.filter(user=request.user)[:20]

    total_earned = sum(t.delta for t in wallet.transactions.all() if t.delta > 0)
    total_spent  = -sum(t.delta for t in wallet.transactions.all() if t.delta < 0)

    return render(request, 'wallet/wallet.html', {
        'wallet': wallet,
        'transactions': txns,
        'coin_requests': coin_requests,
        'total_earned': total_earned,
        'total_spent': total_spent,
    })


@login_required(login_url='/login/')
@require_POST
def request_coins(request):
    try:
        amount = int(request.POST.get('amount', '0'))
    except (TypeError, ValueError):
        amount = 0
    payment_method = (request.POST.get('payment_method') or CoinRequest.PAYMENT_PAYPAL).strip().lower()
    transaction_id = (request.POST.get('transaction_id') or '').strip()
    reason = (request.POST.get('reason') or '').strip()

    if amount <= 0 or amount > 10_000:
        messages.error(request, "Please request between 1 and 10,000 coins.")
        return redirect('wallet_page')

    valid_methods = {choice[0] for choice in CoinRequest.PAYMENT_CHOICES}
    if payment_method not in valid_methods:
        payment_method = CoinRequest.PAYMENT_PAYPAL

    if not transaction_id:
        messages.error(request, "Please enter your payment transaction or confirmation ID.")
        return redirect('wallet_page')

    # Prevent spamming — at most one pending request at a time
    existing = CoinRequest.objects.filter(
        user=request.user, status=CoinRequest.STATUS_PENDING,
    ).first()
    if existing:
        messages.warning(
            request,
            "You already have a pending coin request — please wait for the admin to review it.",
        )
        return redirect('wallet_page')

    usd_amount = (Decimal(amount) / Decimal('50')).quantize(Decimal('0.01'))
    CoinRequest.objects.create(
        user=request.user,
        amount=amount,
        reason=reason,
        payment_method=payment_method,
        transaction_id=transaction_id,
        usd_amount=usd_amount,
    )
    method_display = dict(CoinRequest.PAYMENT_CHOICES).get(payment_method, payment_method)
    messages.success(
        request,
        f"Payment request submitted. Admin will verify your {method_display} transaction and add {amount} RC once approved.",
    )
    return redirect('wallet_page')
