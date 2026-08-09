# -*- coding: utf-8 -*-
from django.urls import path

from app.grok.views.grok import GrokAccountView, GrokLoginView, GrokAccountEnum, GrokTokenExpiryView
from app.grok.views.grok_pool import GrokPoolView, GrokPoolEnum

urlpatterns = [
    path("enum", GrokAccountEnum.as_view()),
    path("", GrokAccountView.as_view()),
    path("token-expiry", GrokTokenExpiryView.as_view()),
    path("login", GrokLoginView.as_view()),
    path("pool", GrokPoolView.as_view()),
    path("pool-enum", GrokPoolEnum.as_view()),

]
