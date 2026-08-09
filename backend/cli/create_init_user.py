import os
import sys
import time

import django

cur_path = os.path.abspath(__file__)
parent = os.path.dirname
sys.path.append(parent(parent(cur_path)))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "app.settings")
django.setup()

if __name__ == "__main__":
    from app.accounts.models import User
    from app.grok.models import GrokAccount, GrokPool
    from app.settings import FREE_ACCOUNT_USERNAME, ADMIN_USERNAME, ADMIN_PASSWORD
    from django.contrib.auth.password_validation import validate_password

    if not ADMIN_USERNAME:
        raise Exception("未设置 超级管理员账密")
    if not ADMIN_PASSWORD:
        raise Exception("ADMIN_PASSWORD 未设置，请设置后再初始化")


    legacy_upstream = GrokAccount.objects.filter(grok_username="grok-sso-upstream").first()
    if legacy_upstream and not legacy_upstream.has_sso:
        for existing_pool in GrokPool.objects.all():
            account_ids = [
                account_id for account_id in (existing_pool.grok_account_list or [])
                if account_id != legacy_upstream.id
            ]
            if account_ids != (existing_pool.grok_account_list or []):
                existing_pool.grok_account_list = account_ids
                existing_pool.updated_time = int(time.time())
                existing_pool.save(update_fields=["grok_account_list", "updated_time"])
        legacy_upstream.delete()

    pool, _ = GrokPool.objects.get_or_create(
        pool_name="default-grok-sso",
        defaults={
            "grok_account_list": [],
            "remark": "默认 Grok SSO 上游池；请在后台录入账号后绑定",
            "created_time": int(time.time()),
            "updated_time": int(time.time()),
        },
    )

    defaults = {
        "remark": "超级管理员",
        "isolated_session": False,
        "grok_pool_list": [pool.id],
    }
    user, created = User.objects.get_or_create(username=ADMIN_USERNAME, defaults=defaults)
    validate_password(ADMIN_PASSWORD, user)
    user.set_password(ADMIN_PASSWORD)
    user.is_staff = True
    user.is_active = True
    user.is_superuser = True
    user.grok_pool_list = [pool.id]

    user.save()
    print("Superuser created.")

    defaults = {
        "remark": "用于免费体验",
        "is_active": False,
        "isolated_session": True,
        "model_limit": [
            {"every_minute": 1, "limit_count": 3, "model_name": "grok-4.5"},
            {"every_minute": 1, "limit_count": 3, "model_name": "grok-4.20"},
            {"every_minute": 1, "limit_count": 3, "model_name": "grok-voice-latest"},
        ],
        "grok_pool_list": [pool.id],
    }
    user, created = User.objects.get_or_create(username=FREE_ACCOUNT_USERNAME, defaults=defaults)
    user.is_superuser = False
    user.grok_pool_list = [pool.id]
    user.save()
    print("Freeuser created.")
