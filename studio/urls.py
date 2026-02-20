from django.urls import path
from . import views


urlpatterns = [
    path('create/', views.create, name='create'),
    path('my-assets/', views.my_assets, name='my_assets'),
    path('generate/', views.prompt_to_image, name='prompt_to_image'),
]