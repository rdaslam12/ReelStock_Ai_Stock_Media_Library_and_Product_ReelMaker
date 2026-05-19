from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import GeneratedImage, GeneratedVideo, UserProfile


@receiver(post_save, sender=User)
def create_profile_for_new_user(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)
    if not instance.is_active:
        GeneratedImage.objects.filter(user=instance, is_published=True).update(is_published=False)
        GeneratedVideo.objects.filter(user=instance, is_published=True).update(is_published=False)


try:
    from allauth.account.signals import user_signed_up
    from allauth.socialaccount.signals import social_account_added
except Exception:  # django-allauth may not be installed until requirements are applied.
    user_signed_up = None
    social_account_added = None


def _mark_profile_incomplete(user):
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.needs_profile_completion = True
    profile.save(update_fields=["needs_profile_completion"])


if user_signed_up:
    @receiver(user_signed_up)
    def mark_social_signup_incomplete(request, user, sociallogin=None, **kwargs):
        if sociallogin is not None:
            _mark_profile_incomplete(user)


if social_account_added:
    @receiver(social_account_added)
    def mark_social_profile_incomplete(request, sociallogin, **kwargs):
        _mark_profile_incomplete(sociallogin.user)
