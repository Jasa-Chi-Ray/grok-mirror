# -*- coding: utf-8 -*-
from django.contrib import admin

from app.grok.models import GrokAccount, GrokPool


@admin.register(GrokAccount)
class GrokTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "grok_username",
        "plan_type",
        "remark",
    )


@admin.register(GrokPool)
class GrokTokenAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "pool_name",
        "grok_account_list",
    )
