import base64
import json
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from django.db import models
from app.fields import EncryptedJSONField, EncryptedTextField


def parse_sso_input(raw_value):
    raw = str(raw_value or "").strip()
    expires = None

    for line in raw.splitlines():
        fields = line.strip().split("\t")
        if len(fields) >= 7 and fields[5].strip() == "sso":
            raw = fields[6].strip()
            try:
                expires = int(fields[4]) or None
            except (TypeError, ValueError):
                expires = None
            break

    match = re.search(r"(?:^|;\s*)sso=([^;\r\n]*)", raw, flags=re.IGNORECASE)
    value = match.group(1).strip() if match else raw
    if not value:
        raise ValueError("sso Cookie 不能为空")
    if any(character in value for character in (";", "\r", "\n")):
        raise ValueError("sso Cookie 值格式无效")

    max_age = re.search(r"(?:^|;\s*)max-age=(-?\d+)", raw, flags=re.IGNORECASE)
    if max_age:
        expires = int(time.time()) + int(max_age.group(1))
    elif expires is None:
        expires_match = re.search(r"(?:^|;\s*)expires=([^;\r\n]+)", raw, flags=re.IGNORECASE)
        if expires_match:
            try:
                expires = int(parsedate_to_datetime(expires_match.group(1).strip()).timestamp())
            except (TypeError, ValueError, OverflowError):
                expires = None

    if expires is None and value.count(".") == 2:
        try:
            payload = value.split(".", 2)[1]
            payload += "=" * (-len(payload) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
            token_exp = decoded.get("exp")
            if isinstance(token_exp, int):
                expires = token_exp
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    return value, expires


def normalize_sso_value(raw_value):
    return parse_sso_input(raw_value)[0]


def parse_sso_expiry(raw_value):
    if isinstance(raw_value, bool) or raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        return int(raw_value) if raw_value > 0 else None

    value = str(raw_value).strip()
    if not value:
        return None
    try:
        timestamp = int(value)
        return timestamp if timestamp > 0 else None
    except ValueError:
        pass

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def build_sso_cookie(raw_value, expires=None):
    value, detected_expires = parse_sso_input(raw_value)
    return {
        "name": "sso",
        "value": value,
        "domain": ".grok.com",
        "path": "/",
        "secure": True,
        "http_only": True,
        "expires": expires if expires is not None else detected_expires,
        "source": "admin-sso",
    }


class GrokPool(models.Model):
    pool_name = models.CharField(unique=True, max_length=32)
    remark = models.CharField(max_length=128, blank=True, verbose_name="备注")
    grok_account_list = models.JSONField(default=list)
    created_time = models.IntegerField(db_index=True, blank=True, verbose_name="创建时间")
    updated_time = models.IntegerField(db_index=True, blank=True, verbose_name="最后修改时间")

class GrokAccount(models.Model):
    grok_username = models.CharField(max_length=64, unique=True)
    auth_status = models.BooleanField(default=True, verbose_name="授权状态")
    plan_type = models.CharField(max_length=32)
    access_token = EncryptedTextField()
    session_token = EncryptedTextField(null=True, blank=True)
    extra_cookies = EncryptedJSONField(default=list, blank=True, verbose_name="额外 Cookie")
    refresh_token = EncryptedTextField(null=True, blank=True)
    refresh_client_id = EncryptedTextField(null=True, blank=True)
    access_token_valid = models.BooleanField(default=False, verbose_name="AccessToken 可用")
    session_token_valid = models.BooleanField(default=False, verbose_name="SessionToken 可用")
    proxy_node_id = models.IntegerField(null=True, blank=True, verbose_name="代理节点")
    last_check_at = models.IntegerField(null=True, blank=True, verbose_name="最近诊断时间")
    last_error = models.TextField(null=True, blank=True, verbose_name="最近诊断错误")
    remark = models.TextField(null=True, blank=True,verbose_name="备注")
    created_time = models.IntegerField(db_index=True, blank=True, verbose_name="创建时间")
    updated_time = models.IntegerField(db_index=True, blank=True, verbose_name="最后修改时间")

    @classmethod
    def get_by_grok_pool_list(cls, grok_pool_list):
        if not grok_pool_list:
            return cls.objects.none()

        grok_account_list = []
        for line in GrokPool.objects.filter(id__in=grok_pool_list).values("grok_account_list"):
            grok_account_list.extend(line["grok_account_list"])

        return cls.objects.filter(id__in=grok_account_list).order_by("-plan_type", "-id")


    @classmethod
    def get_by_id(cls, grok_id):
        return cls.objects.filter(id=grok_id).first()

    @property
    def has_sso(self):
        return any(
            isinstance(cookie, dict)
            and cookie.get("name") == "sso"
            and str(cookie.get("value") or "").strip()
            for cookie in (self.extra_cookies or [])
        )

    @property
    def sso_expires_at(self):
        for cookie in self.extra_cookies or []:
            if isinstance(cookie, dict) and cookie.get("name") == "sso":
                expires = cookie.get("expires")
                return expires if isinstance(expires, int) else None
        return None

    def set_sso(self, raw_value, expires=None):
        cookies = [
            cookie for cookie in (self.extra_cookies or [])
            if not isinstance(cookie, dict) or cookie.get("name") != "sso"
        ]
        cookies.append(build_sso_cookie(raw_value, expires=expires))
        self.extra_cookies = cookies

    def set_sso_expiry(self, expires):
        expires = parse_sso_expiry(expires)
        if expires is None:
            return False
        cookies = list(self.extra_cookies or [])
        for index, cookie in enumerate(cookies):
            if not isinstance(cookie, dict) or cookie.get("name") != "sso":
                continue
            if cookie.get("expires") == expires:
                return False
            updated_cookie = dict(cookie)
            updated_cookie["expires"] = expires
            cookies[index] = updated_cookie
            self.extra_cookies = cookies
            return True
        return False

    def refresh_auth_diagnostics(self, force=False):
        now = int(time.time())
        if not force and self.last_check_at and now - self.last_check_at < 3600:
            return

        from app.utils import req_gateway

        result = req_gateway("post", "/api/diagnose-grok-auth", json={
            "access_token": self.access_token,
            "session_token": self.session_token,
            "extra_cookies": self.extra_cookies,
            "proxy_node_id": self.proxy_node_id,
        })
        self.access_token_valid = bool(result.get("access_token_valid"))
        self.session_token_valid = bool(
            result.get("session_token_valid") or result.get("sso_valid")
        )
        self.auth_status = self.access_token_valid or self.session_token_valid
        self.last_check_at = result.get("last_check_at") or now
        self.last_error = result.get("last_error") or ""
        expiry_updated = self.set_sso_expiry(result.get("sso_expires_at"))

        user_info = result.get("user_info") or {}
        if user_info.get("email"):
            self.grok_username = user_info["email"]
        if user_info.get("plan_type"):
            self.plan_type = user_info["plan_type"]

        self.updated_time = now
        update_fields = [
            "grok_username",
            "plan_type",
            "access_token_valid",
            "session_token_valid",
            "auth_status",
            "last_check_at",
            "last_error",
            "updated_time",
        ]
        if expiry_updated:
            update_fields.append("extra_cookies")
        self.save(update_fields=update_fields)

    @classmethod
    def save_data(cls, data):
        obj = cls.objects.filter(grok_username=data["user_info"]["email"]).first()
        new_obj = obj or cls()
        new_obj.grok_username = data["user_info"]["email"]
        new_obj.plan_type = data["user_info"]["plan_type"]
        new_obj.access_token = data["access_token"]

        if data.get("auth_status") is not None:
            new_obj.auth_status = data["auth_status"]

        if data.get("session_token"):
            new_obj.session_token = data["session_token"]
            new_obj.refresh_token = None
            new_obj.refresh_client_id = None

        if data.get("refresh_token"):
            new_obj.refresh_token = data["refresh_token"]
            new_obj.refresh_client_id = data.get("refresh_client_id") or new_obj.refresh_client_id
            new_obj.session_token = None

        if data.get("extra_cookies") is not None:
            new_obj.extra_cookies = data.get("extra_cookies") or []

        new_obj.access_token_valid = bool(data.get("access_token_valid"))
        new_obj.session_token_valid = bool(data.get("session_token_valid"))
        new_obj.last_check_at = data.get("last_check_at") or int(time.time())
        new_obj.last_error = data.get("last_error") or ""

        new_obj.updated_time = int(time.time())

        if not obj:
            new_obj.created_time = int(time.time())

        new_obj.save()
        return new_obj.id
