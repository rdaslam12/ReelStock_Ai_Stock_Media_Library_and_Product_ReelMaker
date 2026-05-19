from django.urls import path
from . import views

urlpatterns = [
    # Basket
    path('basket/',                 views.basket_page,    name='basket_page'),
    path('basket/add/',             views.basket_add,     name='basket_add'),
    path('basket/remove/<int:item_id>/', views.basket_remove, name='basket_remove'),
    path('basket/clear/',           views.basket_clear,   name='basket_clear'),
    path('basket/confirm/',         views.basket_confirm, name='basket_confirm'),
    path('basket/count/',           views.basket_count,   name='basket_count'),

    # Wallet
    path('wallet/',                 views.wallet_page,    name='wallet_page'),
    path('wallet/request-coins/',   views.request_coins,  name='request_coins'),
]
