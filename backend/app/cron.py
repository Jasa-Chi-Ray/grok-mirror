# myapp/cron.py
import logging
import time

import jwt
import requests
from django.db import transaction

from app.grok.models import GrokAccount
from app.settings import GROK_GATEWAY_URL
from app.settings import GATEWAY_ADMIN_SECRET

logger = logging.getLogger("cron")
DEFAULT_REFRESH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_WINDOW_SECONDS = 100 * 60


def _access_token_is_fresh(access_token):
    try:
        at_info = jwt.decode(access_token, options={"verify_signature": False})
        return int(time.time()) < at_info["exp"] - REFRESH_WINDOW_SECONDS
    except Exception:
        return False


def _update_token(grok_username, grok_token, client_id=None):
    url = GROK_GATEWAY_URL + "/api/get-user-info"
    headers = {
        "Authorization": "Bearer {}".format(GATEWAY_ADMIN_SECRET),
    }
    payload = {"grok_token": grok_token}
    if client_id:
        payload = {
            "auth_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": grok_token,
        }
    res = requests.post(url, headers=headers, json=payload)
    res_json = res.json()

    if res.status_code != 200:
        logger.info("token 更新失败: account=%s status=%s", grok_username, res.status_code)
        message = res_json.get("message", "") if isinstance(res_json, dict) else str(res_json)
        if (
            "token 失效" in message
            or "authentication token" in message
            or "refresh_token" in message
        ):
            logger.warning("token 失效: account=%s status=%s", grok_username, res.status_code)
            return False
        return None

    res_json["auth_status"] = True
    GrokAccount.save_data(res_json)
    return True


def update_access_token():
    for line in GrokAccount.objects.all():
        if _access_token_is_fresh(line.access_token) and line.auth_status:
            continue

        if line.refresh_token:
            with transaction.atomic():
                locked = GrokAccount.objects.select_for_update().get(id=line.id)
                if _access_token_is_fresh(locked.access_token) and locked.auth_status:
                    continue

                client_id = locked.refresh_client_id or DEFAULT_REFRESH_CLIENT_ID
                update_status = _update_token(locked.grok_username, locked.refresh_token, client_id)
                if update_status is False:
                    locked.refresh_token = None
                    locked.save()
                    logger.warning("refresh_token 已经过期: account=%s", locked.grok_username)

        elif line.session_token:
            update_status = _update_token(line.grok_username, line.session_token)
            if update_status is False:
                line.session_token = None
                line.save()
                logger.warning("session_token 已经过期: account=%s", line.grok_username)


def check_access_token():

    need_to_update = int(time.time() - 3600)
    for line in GrokAccount.objects.filter(updated_time__lte=need_to_update, auth_status=True).all():
        if line.access_token:
            if _update_token(line.grok_username, line.access_token) is False:
                line.auth_status = False
                line.updated_time = int(time.time())
                line.save()
                logger.warning(f"access_token 已经过期: {line.grok_username}")
                return
            else:
                line.updated_time = int(time.time())
                line.save()
                logger.info(f"access_token 有效: {line.grok_username}")
