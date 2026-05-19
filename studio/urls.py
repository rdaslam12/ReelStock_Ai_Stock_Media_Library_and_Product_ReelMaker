from django.urls import path
from . import views

urlpatterns = [
    path("create/",                       views.create,              name="create"),
    path("my-assets/",                    views.my_assets,           name="my_assets"),
    path("generate/",                     views.prompt_to_image,     name="prompt_to_image"),
    path("generate/image/",              views.generate_image,      name="generate_image"),
    path("generate/image/save/",         views.save_image,          name="save_image"),
    path("generate/video/",              views.generate_video_text,  name="generate_video_text"),
    path("reel/submit/",                 views.submit_reel,         name="submit_reel"),
    path("reel/status/<int:video_id>/",  views.reel_status,         name="reel_status"),
    path("reel/publish/<int:video_id>/", views.publish_reel,        name="publish_reel"),
]
