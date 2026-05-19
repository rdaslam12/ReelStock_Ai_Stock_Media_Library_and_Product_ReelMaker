from django import forms
from django.contrib.auth.models import User

from .models import UserProfile


class CompleteProfileForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-3",
            "placeholder": "your_username",
            "autocomplete": "username",
        }),
    )
    display_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-3",
            "placeholder": "Your full name",
            "autocomplete": "name",
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        initial = kwargs.setdefault("initial", {})
        if user:
            initial.setdefault("username", user.username)
            initial.setdefault("display_name", user.get_full_name())
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.user and self.user.pk:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def save(self):
        user = self.user
        user.username = self.cleaned_data["username"]
        display_name = self.cleaned_data.get("display_name", "").strip()
        if display_name:
            parts = display_name.split(None, 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
        user.save(update_fields=["username", "first_name", "last_name"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.needs_profile_completion = False
        profile.save(update_fields=["needs_profile_completion"])
        return user
