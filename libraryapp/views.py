import json
import logging
import math
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Avg, Count, F
from django.http import Http404, HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.models import (
    AssetComment,
    AssetRating,
    AssetView,
    Bookmark,
    Collection,
    CollectionItem,
    CommentReaction,
    Follow,
    GeneratedImage,
    GeneratedVideo,
    Notification,
    UserProfile,
)
from moderation.models import TrendingOverride

logger = logging.getLogger(__name__)


def _json_payload(request: HttpRequest):
    try:
        return json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return None


def _published_asset(asset_type: str, asset_id: int):
    if asset_type == "video":
        return get_object_or_404(
            GeneratedVideo,
            pk=asset_id,
            is_published=True,
            status=GeneratedVideo.STATUS_DONE,
        )
    if asset_type == "image":
        return get_object_or_404(GeneratedImage, pk=asset_id, is_published=True)
    return None


def _record_asset_view(request: HttpRequest, asset_type: str, asset):
    since = timezone.now() - timedelta(hours=24)
    lookup = {
        "asset_type": asset_type,
        "asset_id": asset.pk,
        "viewed_at__gte": since,
    }

    if request.user.is_authenticated:
        lookup["user"] = request.user
        create_kwargs = {"user": request.user, "session_key": ""}
    else:
        if not request.session.session_key:
            request.session.create()
        session_key = request.session.session_key
        lookup["session_key"] = session_key
        create_kwargs = {"user": None, "session_key": session_key}

    if AssetView.objects.filter(**lookup).exists():
        return False

    AssetView.objects.create(
        asset_type=asset_type,
        asset_id=asset.pk,
        **create_kwargs,
    )
    model = GeneratedVideo if asset_type == "video" else GeneratedImage
    model.objects.filter(pk=asset.pk).update(view_count=F("view_count") + 1)
    asset.view_count = (asset.view_count or 0) + 1
    return True


def library(request: HttpRequest):
    media_type = request.GET.get('type', 'images')   # 'images' | 'videos'
    search = request.GET.get('search', '').strip()
    category = request.GET.get('category', '').strip()

    if media_type == 'videos':
        qs = GeneratedVideo.objects.filter(
            is_published=True, status='done'
        ).select_related('user__profile')
        if search:
            qs = qs.filter(title__icontains=search) | qs.filter(product_name__icontains=search)
        if category:
            qs = qs.filter(category__iexact=category)
        categories = list(
            GeneratedVideo.objects.filter(is_published=True, status='done')
            .values_list('category', flat=True).distinct().order_by('category')
        )
        assets = list(qs[:60])
        logger.debug(
            "library: serving %s published videos; playback urls=%s",
            len(assets),
            [(v.pk, v.playback_url, v.video_file.name if v.video_file else '', v.video_url) for v in assets[:5]],
        )
    else:
        qs = GeneratedImage.objects.filter(
            is_published=True
        ).select_related('user__profile')
        if search:
            qs = qs.filter(title__icontains=search) | qs.filter(prompt__icontains=search)
        if category:
            qs = qs.filter(style__iexact=category)
        categories = list(
            GeneratedImage.objects.filter(is_published=True)
            .values_list('style', flat=True).distinct().order_by('style')
        )
        assets = list(qs[:60])

    return render(request, 'libraryapp/library.html', {
        'assets': assets,
        'media_type': media_type,
        'search_query': search,
        'current_category': category,
        'categories': [c for c in categories if c],
    })


def asset_detail(request: HttpRequest, asset_type: str, asset_id: int):
    if asset_type not in ('image', 'video'):
        raise Http404("Unknown asset type")
    if asset_type == 'video':
        asset = get_object_or_404(
            GeneratedVideo,
            pk=asset_id,
            is_published=True,
            status=GeneratedVideo.STATUS_DONE,
        )
        if asset.sync_video_file_from_url():
            asset.save(update_fields=['video_file', 'updated_at'])
            logger.info(
                "asset_detail: backfilled video_file for video_id=%s from video_url=%s -> %s",
                asset.pk,
                asset.video_url,
                asset.video_file.name,
            )
        logger.debug(
            "asset_detail: video_id=%s playback_url=%s video_file=%s raw_video_url=%s",
            asset.pk,
            asset.playback_url,
            asset.video_file.name if asset.video_file else '',
            asset.video_url,
        )
        other = GeneratedVideo.objects.filter(
            user=asset.user, is_published=True, status='done'
        ).exclude(pk=asset_id)[:6]
    else:
        asset = get_object_or_404(GeneratedImage, pk=asset_id, is_published=True)
        other = GeneratedImage.objects.filter(
            user=asset.user, is_published=True
        ).exclude(pk=asset_id)[:6]

    _record_asset_view(request, asset_type, asset)
    profile, _ = UserProfile.objects.get_or_create(user=asset.user)
    public_url = request.build_absolute_uri(request.path)

    rating_agg = AssetRating.objects.filter(
        asset_type=asset_type, asset_id=asset_id
    ).aggregate(avg=Avg('score'), count=Count('id'))
    avg_rating = round(rating_agg['avg'] or 0, 1)
    rating_count = rating_agg['count']
    user_rating = None
    if request.user.is_authenticated:
        rating = AssetRating.objects.filter(
            user=request.user, asset_type=asset_type, asset_id=asset_id
        ).first()
        user_rating = rating.score if rating else None

    top_comments = (
        AssetComment.objects
        .filter(asset_type=asset_type, asset_id=asset_id, parent__isnull=True)
        .select_related('user')
        .prefetch_related('replies__user', 'replies__reactions__user', 'reactions__user')
        .order_by('created_at')
    )

    def reaction_summary(comment):
        counts = {}
        user_reacted = set()
        for reaction in comment.reactions.all():
            counts[reaction.emoji] = counts.get(reaction.emoji, 0) + 1
            if request.user.is_authenticated and reaction.user_id == request.user.id:
                user_reacted.add(reaction.emoji)
        return counts, user_reacted

    comments_data = []
    for comment in top_comments:
        reaction_counts, user_reacted = reaction_summary(comment)
        replies_data = []
        for reply in comment.replies.all():
            reply_counts, reply_user_reacted = reaction_summary(reply)
            replies_data.append({
                'obj': reply,
                'reaction_counts': reply_counts,
                'user_reacted': reply_user_reacted,
            })
        comments_data.append({
            'obj': comment,
            'reaction_counts': reaction_counts,
            'user_reacted': user_reacted,
            'replies': replies_data,
        })

    is_creator = request.user.is_authenticated and request.user == asset.user
    is_bookmarked = False
    is_following_creator = False
    user_collections = []
    if request.user.is_authenticated:
        is_bookmarked = Bookmark.objects.filter(
            user=request.user, asset_type=asset_type, asset_id=asset_id
        ).exists()
        is_following_creator = Follow.objects.filter(
            follower=request.user, following=asset.user
        ).exists()
        user_collections = list(Collection.objects.filter(user=request.user))

    return render(request, 'libraryapp/asset_detail.html', {
        'asset': asset,
        'asset_type': asset_type,
        'profile': profile,
        'other_assets': other,
        'avg_rating': avg_rating,
        'rating_count': rating_count,
        'user_rating': user_rating,
        'comments_data': comments_data,
        'is_creator': is_creator,
        'emoji_choices': CommentReaction.EMOJI_CHOICES,
        'is_bookmarked': is_bookmarked,
        'is_following_creator': is_following_creator,
        'user_collections': user_collections,
        'public_url': public_url,
        'facebook_share_url': f"https://www.facebook.com/sharer/sharer.php?u={public_url}",
    })


@login_required
@require_POST
def rate_asset(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    asset_type = data.get('asset_type')
    try:
        asset_id = int(data.get('asset_id'))
        score = int(data.get('score'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid'}, status=400)

    if asset_type not in ('image', 'video') or score not in range(1, 6):
        return JsonResponse({'error': 'invalid'}, status=400)
    _published_asset(asset_type, asset_id)

    AssetRating.objects.update_or_create(
        user=request.user,
        asset_type=asset_type,
        asset_id=asset_id,
        defaults={'score': score},
    )

    agg = AssetRating.objects.filter(
        asset_type=asset_type, asset_id=asset_id
    ).aggregate(avg=Avg('score'), count=Count('id'))

    return JsonResponse({
        'avg': round(agg['avg'] or 0, 1),
        'count': agg['count'],
        'user_score': score,
    })


@login_required
@require_POST
def post_comment(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    asset_type = data.get('asset_type')
    try:
        asset_id = int(data.get('asset_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid'}, status=400)
    body = data.get('body', '').strip()
    parent_id = data.get('parent_id')

    if not body or asset_type not in ('image', 'video') or len(body) > 1000:
        return JsonResponse({'error': 'invalid'}, status=400)

    asset_obj = _published_asset(asset_type, asset_id)
    parent = None
    if parent_id:
        parent = get_object_or_404(
            AssetComment,
            pk=parent_id,
            asset_type=asset_type,
            asset_id=asset_id,
        )

    comment = AssetComment.objects.create(
        user=request.user,
        asset_type=asset_type,
        asset_id=asset_id,
        parent=parent,
        body=body,
    )

    if parent and parent.user != request.user:
        Notification.objects.create(
            recipient=parent.user,
            actor=request.user,
            notif_type=Notification.NOTIF_REPLY,
            asset_type=asset_type,
            asset_id=asset_id,
            comment=comment,
        )
    elif not parent and asset_obj.user != request.user:
        Notification.objects.create(
            recipient=asset_obj.user,
            actor=request.user,
            notif_type=Notification.NOTIF_COMMENT,
            asset_type=asset_type,
            asset_id=asset_id,
            comment=comment,
        )

    return JsonResponse({
        'id': comment.id,
        'body': comment.body,
        'user': comment.user.get_full_name() or comment.user.username,
        'username': comment.user.username,
        'created_at': comment.created_at.strftime('%b %d, %Y'),
        'is_reply': comment.is_reply,
        'parent_id': parent_id,
    })


@login_required
@require_POST
def delete_comment(request: HttpRequest, comment_id: int):
    comment = get_object_or_404(AssetComment, pk=comment_id)
    if comment.user != request.user:
        is_asset_creator = False
        if comment.asset_type == 'image':
            is_asset_creator = GeneratedImage.objects.filter(
                pk=comment.asset_id, user=request.user
            ).exists()
        elif comment.asset_type == 'video':
            is_asset_creator = GeneratedVideo.objects.filter(
                pk=comment.asset_id, user=request.user
            ).exists()
        if not is_asset_creator:
            return JsonResponse({'error': 'forbidden'}, status=403)
    comment.delete()
    return JsonResponse({'deleted': True})


@login_required
@require_POST
def toggle_reaction(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    try:
        comment_id = int(data.get('comment_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid'}, status=400)
    emoji = data.get('emoji', '👍')

    if emoji not in CommentReaction.EMOJI_CHOICES:
        return JsonResponse({'error': 'invalid emoji'}, status=400)

    comment = get_object_or_404(AssetComment, pk=comment_id)
    existing = CommentReaction.objects.filter(
        user=request.user, comment=comment, emoji=emoji
    ).first()

    if existing:
        existing.delete()
        active = False
    else:
        CommentReaction.objects.create(user=request.user, comment=comment, emoji=emoji)
        active = True

    count = CommentReaction.objects.filter(comment=comment, emoji=emoji).count()
    return JsonResponse({'emoji': emoji, 'count': count, 'active': active})


def creator_profile(request: HttpRequest, username: str):
    creator = get_object_or_404(User, username=username)
    profile, _ = UserProfile.objects.get_or_create(user=creator)
    images = GeneratedImage.objects.filter(user=creator, is_published=True)
    videos = GeneratedVideo.objects.filter(user=creator, is_published=True, status='done')
    follower_count = Follow.objects.filter(following=creator).count()
    following_count = Follow.objects.filter(follower=creator).count()
    is_following = False
    if request.user.is_authenticated and request.user != creator:
        is_following = Follow.objects.filter(follower=request.user, following=creator).exists()
    return render(request, 'libraryapp/creator_profile.html', {
        'creator': creator,
        'profile': profile,
        'images': images,
        'videos': videos,
        'follower_count': follower_count,
        'following_count': following_count,
        'is_following': is_following,
    })


@login_required
@require_POST
def toggle_follow(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    username = data.get('username', '')
    target = get_object_or_404(User, username=username)
    if target == request.user:
        return JsonResponse({'error': 'cannot follow yourself'}, status=400)

    existing = Follow.objects.filter(follower=request.user, following=target).first()
    if existing:
        existing.delete()
        following = False
    else:
        Follow.objects.create(follower=request.user, following=target)
        following = True
        Notification.objects.create(
            recipient=target,
            actor=request.user,
            notif_type=Notification.NOTIF_FOLLOW,
        )

    count = Follow.objects.filter(following=target).count()
    return JsonResponse({'following': following, 'follower_count': count})


@login_required
@require_POST
def toggle_bookmark(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    asset_type = data.get('asset_type')
    try:
        asset_id = int(data.get('asset_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid'}, status=400)
    if asset_type not in ('image', 'video'):
        return JsonResponse({'error': 'invalid'}, status=400)
    _published_asset(asset_type, asset_id)

    existing = Bookmark.objects.filter(
        user=request.user, asset_type=asset_type, asset_id=asset_id
    ).first()
    if existing:
        existing.delete()
        bookmarked = False
    else:
        Bookmark.objects.create(user=request.user, asset_type=asset_type, asset_id=asset_id)
        bookmarked = True

    count = Bookmark.objects.filter(asset_type=asset_type, asset_id=asset_id).count()
    return JsonResponse({'bookmarked': bookmarked, 'count': count})


@login_required
def my_collections(request: HttpRequest):
    collections = Collection.objects.filter(user=request.user).annotate(
        item_count=Count('items')
    )
    return render(request, 'libraryapp/my_collections.html', {
        'collections': collections,
    })


@login_required
def collection_detail(request: HttpRequest, collection_id: int):
    collection = get_object_or_404(Collection, pk=collection_id)
    if not collection.is_public and collection.user != request.user:
        return redirect('library')

    resolved = []
    for item in collection.items.all():
        if item.asset_type == 'image':
            try:
                obj = GeneratedImage.objects.get(pk=item.asset_id, is_published=True)
                resolved.append({'type': 'image', 'obj': obj, 'item': item})
            except GeneratedImage.DoesNotExist:
                pass
        else:
            try:
                obj = GeneratedVideo.objects.get(
                    pk=item.asset_id,
                    is_published=True,
                    status=GeneratedVideo.STATUS_DONE,
                )
                resolved.append({'type': 'video', 'obj': obj, 'item': item})
            except GeneratedVideo.DoesNotExist:
                pass
    return render(request, 'libraryapp/collection_detail.html', {
        'collection': collection,
        'resolved': resolved,
        'is_owner': collection.user == request.user,
    })


@login_required
@require_POST
def create_collection(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    name = data.get('name', '').strip()
    description = data.get('description', '').strip()
    if not name:
        return JsonResponse({'error': 'name required'}, status=400)
    collection = Collection.objects.create(
        user=request.user,
        name=name,
        description=description,
    )
    return JsonResponse({'id': collection.id, 'name': collection.name})


@login_required
@require_POST
def add_to_collection(request: HttpRequest):
    data = _json_payload(request)
    if data is None:
        return JsonResponse({'error': 'invalid json'}, status=400)

    try:
        collection_id = int(data.get('collection_id'))
        asset_id = int(data.get('asset_id'))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'invalid'}, status=400)
    asset_type = data.get('asset_type')
    if asset_type not in ('image', 'video'):
        return JsonResponse({'error': 'invalid'}, status=400)
    _published_asset(asset_type, asset_id)

    collection = get_object_or_404(Collection, pk=collection_id, user=request.user)
    _, created = CollectionItem.objects.get_or_create(
        collection=collection,
        asset_type=asset_type,
        asset_id=asset_id,
    )
    return JsonResponse({'added': created, 'collection': collection.name})


@login_required
@require_POST
def remove_from_collection(request: HttpRequest, item_id: int):
    item = get_object_or_404(CollectionItem, pk=item_id, collection__user=request.user)
    item.delete()
    return JsonResponse({'removed': True})


@login_required
@require_POST
def delete_collection(request: HttpRequest, collection_id: int):
    collection = get_object_or_404(Collection, pk=collection_id, user=request.user)
    collection.delete()
    return JsonResponse({'deleted': True})


@login_required
def my_bookmarks(request: HttpRequest):
    bookmarks = Bookmark.objects.filter(user=request.user)
    resolved = []
    for bookmark in bookmarks:
        if bookmark.asset_type == 'image':
            try:
                obj = GeneratedImage.objects.get(pk=bookmark.asset_id, is_published=True)
                resolved.append({'type': 'image', 'obj': obj, 'bookmark': bookmark})
            except GeneratedImage.DoesNotExist:
                pass
        else:
            try:
                obj = GeneratedVideo.objects.get(
                    pk=bookmark.asset_id,
                    is_published=True,
                    status=GeneratedVideo.STATUS_DONE,
                )
                resolved.append({'type': 'video', 'obj': obj, 'bookmark': bookmark})
            except GeneratedVideo.DoesNotExist:
                pass
    return render(request, 'libraryapp/my_bookmarks.html', {'resolved': resolved})


@login_required
def following_feed(request: HttpRequest):
    followed_ids = Follow.objects.filter(follower=request.user).values_list('following_id', flat=True)
    images = GeneratedImage.objects.filter(
        user__in=followed_ids, is_published=True
    ).select_related('user__profile').order_by('-created_at')[:40]
    videos = GeneratedVideo.objects.filter(
        user__in=followed_ids, is_published=True, status='done'
    ).select_related('user__profile').order_by('-created_at')[:40]

    feed = []
    for image in images:
        feed.append({'type': 'image', 'obj': image, 'ts': image.created_at})
    for video in videos:
        feed.append({'type': 'video', 'obj': video, 'ts': video.created_at})
    feed.sort(key=lambda item: item['ts'], reverse=True)

    return render(request, 'libraryapp/following_feed.html', {
        'feed': feed[:60],
        'followed_count': len(followed_ids),
    })


def trending(request: HttpRequest):
    since = timezone.now() - timedelta(days=7)

    def score_asset_type(asset_type):
        rating_rows = {
            row['asset_id']: row
            for row in AssetRating.objects.filter(asset_type=asset_type, created_at__gte=since)
            .values('asset_id')
            .annotate(avg=Avg('score'), cnt=Count('id'))
        }
        comment_counts = {
            row['asset_id']: row['cnt']
            for row in AssetComment.objects.filter(asset_type=asset_type, created_at__gte=since)
            .values('asset_id').annotate(cnt=Count('id'))
        }
        view_counts = {
            row['asset_id']: row['cnt']
            for row in AssetView.objects.filter(asset_type=asset_type, viewed_at__gte=since)
            .values('asset_id').annotate(cnt=Count('id'))
        }
        asset_ids = set(rating_rows) | set(comment_counts) | set(view_counts)
        scored = []
        for asset_id in asset_ids:
            rating = rating_rows.get(asset_id, {})
            avg = rating.get('avg') or 0
            rating_count = rating.get('cnt') or 0
            comments = comment_counts.get(asset_id, 0)
            views = view_counts.get(asset_id, 0)
            score = (
                views * 1.0
                + comments * 1.8
                + (avg * math.log(rating_count + 1) * 2.0)
            )
            scored.append((score, asset_id))
        scored.sort(reverse=True)
        return [asset_id for _, asset_id in scored[:20]]

    manual_images = [
        item.image for item in TrendingOverride.objects
        .filter(asset_type='image', is_active=True, image__is_published=True)
        .select_related('image__user')
        .order_by('order', '-created_at')
        if item.image
    ]
    manual_image_ids = {image.pk for image in manual_images}
    top_image_ids = [asset_id for asset_id in score_asset_type('image') if asset_id not in manual_image_ids]
    image_map = {
        image.pk: image
        for image in GeneratedImage.objects.filter(
            pk__in=top_image_ids,
            is_published=True,
        ).select_related('user')
    }
    top_images = manual_images + [image_map[asset_id] for asset_id in top_image_ids if asset_id in image_map]

    manual_videos = [
        item.video for item in TrendingOverride.objects
        .filter(asset_type='video', is_active=True, video__is_published=True, video__status=GeneratedVideo.STATUS_DONE)
        .select_related('video__user')
        .order_by('order', '-created_at')
        if item.video
    ]
    manual_video_ids = {video.pk for video in manual_videos}
    top_video_ids = [asset_id for asset_id in score_asset_type('video') if asset_id not in manual_video_ids]
    video_map = {
        video.pk: video
        for video in GeneratedVideo.objects.filter(
            pk__in=top_video_ids,
            is_published=True,
            status=GeneratedVideo.STATUS_DONE,
        ).select_related('user')
    }
    top_videos = manual_videos + [video_map[asset_id] for asset_id in top_video_ids if asset_id in video_map]

    if not top_images:
        top_images = list(
            GeneratedImage.objects.filter(is_published=True)
            .select_related('user')
            .order_by('-created_at')[:20]
        )
    if not top_videos:
        top_videos = list(
            GeneratedVideo.objects.filter(is_published=True, status='done')
            .select_related('user')
            .order_by('-created_at')[:20]
        )

    return render(request, 'libraryapp/trending.html', {
        'top_images': top_images,
        'top_videos': top_videos,
    })


@login_required
def notifications_page(request: HttpRequest):
    notifications = list(
        Notification.objects.filter(recipient=request.user)
        .select_related('actor')
        .order_by('-created_at')[:50]
    )
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return render(request, 'libraryapp/notifications.html', {'notifs': notifications})


@login_required
def notifications_count(request: HttpRequest):
    count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    return JsonResponse({'count': count})
