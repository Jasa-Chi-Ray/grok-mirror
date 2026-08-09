from unittest.mock import patch
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APIRequestFactory, force_authenticate

from app.accounts.models import User, VisitLog
from app.accounts.views import ChangePasswordView, GetMirrorToken, VisitLogView
from app.accounts.authentication import AUTH_COOKIE_NAME, ExpiringCookieTokenAuthentication
from app.accounts.views.cfg import AccessControlView
from app.accounts.views.login import (
    AccountLogin,
    AccountLogout,
    AccountRegister,
    UserFreeLoginView,
    verify_turnstile,
)
from app.grok.models import GrokAccount, GrokPool, parse_sso_expiry
from app.grok.serializers import AddGrokTokenSerializer, GrokLoginSerializer, ShowGrokTokenSerializer
from app.grok.views.grok import GrokAccountView, GrokLoginView
from app.settings import ADMIN_USERNAME, FREE_ACCOUNT_USERNAME
from app.utils import get_client_ip


class SecurityRegressionTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def test_empty_account_pool_is_fail_closed(self):
        self.assertFalse(GrokAccount.get_by_grok_pool_list([]).exists())

    def test_login_serializer_rejects_removed_api_mode(self):
        serializer = GrokLoginSerializer(data={"login_mode": "api"})
        self.assertFalse(serializer.is_valid())

    def test_account_input_only_accepts_sso(self):
        serializer = AddGrokTokenSerializer(data={"sso": "sso-secret"})
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(set(serializer.fields), {"sso"})

        missing_sso = AddGrokTokenSerializer(data={})
        self.assertFalse(missing_sso.is_valid())

    def test_client_ip_prefers_gateway_forwarded_address(self):
        request = self.factory.get(
            "/0x/user/visit-log",
            HTTP_X_GROK_MIRROR_CLIENT_IP="203.0.113.9",
            HTTP_X_FORWARDED_FOR="172.18.0.1",
            REMOTE_ADDR="172.18.0.2",
        )
        self.assertEqual(get_client_ip(request), "203.0.113.9")

    def test_client_ip_ignores_invalid_values_and_uses_remote_address(self):
        request = self.factory.get(
            "/0x/user/visit-log",
            HTTP_X_GROK_MIRROR_CLIENT_IP="invalid",
            REMOTE_ADDR="2001:db8::9",
        )
        self.assertEqual(get_client_ip(request), "2001:db8::9")

    def test_access_control_requires_admin(self):
        user = User.objects.create_user(username="normal-user", password="password-123")
        request = self.factory.post("/0x/user/access-control", {"hash_paths": []}, format="json")
        force_authenticate(request, user=user)
        response = AccessControlView.as_view()(request)
        self.assertEqual(response.status_code, 403)

    @patch("app.accounts.views.login.req_gateway", return_value={"message": "退出成功"})
    def test_logout_revokes_drf_and_gateway_sessions(self, req_gateway):
        user = User.objects.create_user(username="logout-user", password="password-123")
        token = Token.objects.create(user=user)
        request = self.factory.post("/0x/user/logout", {}, format="json")
        force_authenticate(request, user=user, token=token)
        response = AccountLogout.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Token.objects.filter(key=token.key).exists())
        req_gateway.assert_called_once_with(
            "post",
            "/api/logout",
            json={"user_name": "logout-user"},
        )

    def test_stale_auth_cookie_does_not_block_public_login_with_csrf_403(self):
        user = User.objects.create_user(username="stale-login", password="Strong-password-123!")
        token = Token.objects.create(user=user)
        request = self.factory.post(
            "/0x/user/login",
            {"username": "stale-login", "password": "wrong-password"},
            format="json",
            HTTP_COOKIE=f"{AUTH_COOKIE_NAME}={token.key}",
        )

        response = AccountLogin.as_view()(request)

        self.assertEqual(response.status_code, 400)

    @override_settings(CSRF_TRUSTED_ORIGINS=["https://mirror.example"])
    @patch("app.accounts.views.login.TURNSTILE_ENABLED", False)
    def test_admin_login_issues_csrf_cookie_for_unsafe_api_requests(self):
        User.objects.create_superuser(username="csrf-admin", password="Strong-password-123!")
        client = APIClient(enforce_csrf_checks=True)

        login = client.post(
            "/0x/user/login",
            {"username": "csrf-admin", "password": "Strong-password-123!"},
            format="json",
            HTTP_USER_AGENT="security-regression-test",
            HTTP_ORIGIN="https://mirror.example",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(login.status_code, 200)
        self.assertIn("csrftoken", login.cookies)
        self.assertTrue(login.data["csrf_token"])

        rejected = client.post(
            "/0x/user/",
            {},
            format="json",
            HTTP_ORIGIN="https://mirror.example",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertEqual(rejected.status_code, 403)

        me = client.get("/0x/user/me")
        self.assertEqual(me.status_code, 200)
        self.assertTrue(me.data["csrf_token"])

        response = client.post(
            "/0x/user/",
            {},
            format="json",
            HTTP_X_CSRFTOKEN=me.data["csrf_token"],
            HTTP_ORIGIN="https://mirror.example",
            HTTP_REFERER="https://mirror.example/admin/",
            HTTP_X_FORWARDED_PROTO="https",
        )
        self.assertNotEqual(response.status_code, 403)

    @patch("app.accounts.views.login.save_visit_log")
    def test_free_login_keeps_shared_token_but_rotates_visitor_subject(self, _save_visit_log):
        User.objects.create_user(username=FREE_ACCOUNT_USERNAME, password="password-123")
        view = UserFreeLoginView.as_view()
        first = view(self.factory.post("/0x/user/login-free", {}, format="json"))
        second = view(self.factory.post("/0x/user/login-free", {}, format="json"))
        self.assertNotIn("admin_token", first.data)
        self.assertEqual(
            first.cookies[AUTH_COOKIE_NAME].value,
            second.cookies[AUTH_COOKIE_NAME].value,
        )
        self.assertNotEqual(
            first.cookies["free_session"].value,
            second.cookies["free_session"].value,
        )
        self.assertTrue(first.cookies["free_session"]["httponly"])
        self.assertTrue(first.cookies[AUTH_COOKIE_NAME]["httponly"])

    @override_settings(API_TOKEN_TTL_SECONDS=60)
    def test_expired_drf_token_is_rejected(self):
        user = User.objects.create_user(username="expired-token", password="password-123")
        token = Token.objects.create(user=user)
        Token.objects.filter(pk=token.pk).update(created=timezone.now() - timedelta(seconds=61))
        token.refresh_from_db()
        with patch("app.utils.req_gateway") as req_gateway:
            with self.assertRaises(Exception):
                request = self.factory.get(
                    "/0x/user/me",
                    HTTP_AUTHORIZATION=f"Token {token.key}",
                )
                ExpiringCookieTokenAuthentication().authenticate(request)
            req_gateway.assert_called_once_with(
                "post", "/api/logout", json={"user_name": user.username}
            )

    @patch("app.accounts.views.login.req_gateway")
    @patch("app.accounts.views.login.ALLOW_REGISTER", True)
    @patch("app.accounts.views.login.TURNSTILE_ENABLED", False)
    def test_registration_conflict_is_checked_before_upstream_write(self, req_gateway):
        User.objects.create_user(username="existing-user", password="Strong-password-123!")
        request = self.factory.post(
            "/0x/user/register",
            {
                "username": "existing-user",
                "password": "Another-strong-password-123!",
                "grok_token": "upstream-secret",
            },
            format="json",
        )
        response = AccountRegister.as_view()(request)
        self.assertEqual(response.status_code, 400)
        req_gateway.assert_not_called()

    @patch("app.accounts.views.req_gateway", return_value={"message": "ok"})
    def test_password_change_revokes_old_token_and_issues_new_cookie(self, _req_gateway):
        user = User.objects.create_user(
            username="change-password-user",
            password="Old-strong-password-123!",
        )
        old_token = Token.objects.create(user=user)
        request = self.factory.post(
            "/0x/user/change-password",
            {
                "current_password": "Old-strong-password-123!",
                "new_password": "New-strong-password-456!",
            },
            format="json",
        )
        force_authenticate(request, user=user, token=old_token)
        response = ChangePasswordView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Token.objects.filter(key=old_token.key).exists())
        self.assertTrue(response.cookies[AUTH_COOKIE_NAME]["httponly"])

    def test_grok_credentials_are_encrypted_at_rest(self):
        account = GrokAccount.objects.create(
            grok_username="encrypted@example.com",
            plan_type="plus",
            access_token="plain-access-secret",
            session_token="plain-session-secret",
            extra_cookies=[{"name": "session", "value": "plain-cookie-secret"}],
            created_time=1,
            updated_time=1,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT access_token, session_token, extra_cookies FROM grok_grokaccount WHERE id = %s",
                [account.id],
            )
            stored = cursor.fetchone()
        self.assertTrue(stored[0].startswith("enc:v1:"))
        self.assertTrue(stored[1].startswith("enc:v1:"))
        self.assertTrue(stored[2].startswith("enc:v1:"))
        self.assertNotIn("plain", "".join(stored))

    def test_account_serializer_excludes_raw_credentials(self):
        account = GrokAccount.objects.create(
            grok_username="shared@example.com",
            plan_type="plus",
            access_token="secret-access",
            session_token="secret-session",
            refresh_token="secret-refresh",
            refresh_client_id="secret-client",
            extra_cookies=[{"name": "secret", "value": "cookie"}],
            created_time=1,
            updated_time=1,
        )
        data = ShowGrokTokenSerializer(account).data
        for field in (
            "access_token",
            "session_token",
            "refresh_token",
            "refresh_client_id",
            "extra_cookies",
        ):
            self.assertNotIn(field, data)

    def test_sso_is_encrypted_at_rest_and_only_exposes_configuration_state(self):
        serializer = AddGrokTokenSerializer(data={
            "sso": "sso=plain-sso-secret",
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        account = GrokAccount.objects.create(
            grok_username="sso-account",
            plan_type="Grok SSO",
            access_token="",
            created_time=1,
            updated_time=1,
        )
        account.set_sso(serializer.validated_data["sso"])
        account.save(update_fields=["extra_cookies"])

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT extra_cookies FROM grok_grokaccount WHERE id = %s",
                [account.id],
            )
            stored = cursor.fetchone()[0]
        self.assertTrue(stored.startswith("enc:v1:"))
        self.assertNotIn("plain-sso-secret", stored)

        data = ShowGrokTokenSerializer(GrokAccount.objects.get(id=account.id)).data
        self.assertTrue(data["has_sso"])
        self.assertNotIn("extra_cookies", data)
        self.assertNotIn("sso", data)

    def test_sso_expiry_is_extracted_from_set_cookie(self):
        serializer = AddGrokTokenSerializer(data={
            "sso": "sso=secret-value; Expires=Wed, 05 Aug 2027 07:14:20 GMT; Path=/",
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        account = GrokAccount.objects.create(
            grok_username="expiring-sso",
            plan_type="Grok SSO",
            access_token="",
            created_time=1,
            updated_time=1,
        )
        account.set_sso(
            serializer.validated_data["sso"],
            expires=serializer.validated_data["sso_expires"],
        )
        account.save(update_fields=["extra_cookies"])
        self.assertGreater(account.sso_expires_at, 1_800_000_000)
        self.assertEqual(ShowGrokTokenSerializer(account).data["sso_exp"], account.sso_expires_at)

    @patch("app.grok.views.grok.req_gateway", return_value={
        "sso_valid": True,
        "last_check_at": 1234,
        "last_error": "",
        "user_info": {"email": "verified@example.com", "plan_type": "plus"},
    })
    def test_admin_creates_sso_account_with_gateway_detected_name(self, req_gateway):
        admin = User.objects.create_superuser(
            username="sso-admin",
            password="Admin-password-9384!",
        )
        request = self.factory.post(
            "/0x/grok",
            {
                "sso": "backend-account-secret",
            },
            format="json",
        )
        force_authenticate(request, user=admin)
        response = GrokAccountView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        account = GrokAccount.objects.get(grok_username="verified@example.com")
        self.assertTrue(account.has_sso)
        self.assertTrue(account.auth_status)
        self.assertTrue(account.session_token_valid)
        self.assertEqual(account.last_check_at, 1234)
        payload = req_gateway.call_args.kwargs["json"]
        self.assertEqual(payload["extra_cookies"][0]["name"], "sso")

    @patch("app.utils.req_gateway", return_value={
        "access_token_valid": False,
        "session_token_valid": False,
        "sso_valid": True,
        "sso_expires_at": "2027-08-05T07:14:20.000Z",
        "last_check_at": 1234,
        "last_error": "",
        "user_info": {"email": "verified@example.com", "plan_type": "plus"},
    })
    def test_sso_diagnostics_are_verified_by_gateway(self, req_gateway):
        account = GrokAccount.objects.create(
            grok_username="pending-sso-account",
            plan_type="Grok SSO",
            access_token="",
            created_time=1,
            updated_time=1,
        )
        account.set_sso("verified-sso-secret")
        account.save(update_fields=["extra_cookies"])

        account.refresh_auth_diagnostics(force=True)

        account.refresh_from_db()
        self.assertTrue(account.session_token_valid)
        self.assertTrue(account.auth_status)
        self.assertEqual(account.grok_username, "verified@example.com")
        self.assertEqual(
            account.sso_expires_at,
            parse_sso_expiry("2027-08-05T07:14:20.000Z"),
        )
        payload = req_gateway.call_args.kwargs["json"]
        self.assertEqual(payload["extra_cookies"][0]["name"], "sso")

    @patch("app.accounts.views.req_gateway", return_value=[])
    def test_mirror_token_request_contains_selected_account_credentials(self, req_gateway):
        account = GrokAccount.objects.create(
            grok_username="mirror-api@example.com",
            plan_type="plus",
            access_token="mirror-access-secret",
            auth_status=True,
            access_token_valid=True,
            created_time=1,
            updated_time=1,
        )
        pool = GrokPool.objects.create(
            pool_name="mirror-token-pool",
            grok_account_list=[account.id],
            created_time=1,
            updated_time=1,
        )
        user = User.objects.create_user(
            username="mirror-token-user",
            password="User-password-9384!",
            grok_pool_list=[pool.id],
        )
        request = self.factory.get("/0x/user/get-mirror-token")
        force_authenticate(request, user=user)

        response = GetMirrorToken.as_view()(request)

        self.assertEqual(response.status_code, 200)
        payload = req_gateway.call_args.kwargs["json"]
        self.assertNotIn("grok_list", payload)
        self.assertEqual(payload["grok_accounts"][0]["access_token"], "mirror-access-secret")
        self.assertEqual(payload["grok_accounts"][0]["login_mode"], "api")

    @patch("app.grok.views.grok.req_gateway", return_value={"login_url": "/", "mirror_token": "mirror"})
    def test_selected_account_sso_is_sent_to_gateway_login(self, req_gateway):
        account = GrokAccount.objects.create(
            grok_username="selected-sso-account",
            plan_type="Grok SSO",
            access_token="",
            auth_status=True,
            session_token_valid=True,
            created_time=1,
            updated_time=1,
        )
        account.set_sso("selected-account-secret")
        account.save(update_fields=["extra_cookies"])
        pool = GrokPool.objects.create(
            pool_name="selected-sso-pool",
            grok_account_list=[account.id],
            created_time=1,
            updated_time=1,
        )
        user = User.objects.create_user(
            username="selected-sso-user",
            password="User-password-9384!",
            grok_pool_list=[pool.id],
        )
        request = self.factory.post(
            "/0x/grok/login",
            {"grok_id": account.id, "login_mode": "web"},
            format="json",
            HTTP_USER_AGENT="test-agent",
            REMOTE_ADDR="127.0.0.1",
        )
        force_authenticate(request, user=user)
        response = GrokLoginView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        login_call = next(call for call in req_gateway.call_args_list if call.args[1] == "/api/login")
        payload = login_call.kwargs["json"]
        self.assertEqual(payload["grok_username"], account.grok_username)
        self.assertEqual(payload["extra_cookies"][0]["name"], "sso")
        self.assertEqual(payload["extra_cookies"][0]["value"], "selected-account-secret")

    def test_clear_visit_logs_preserves_admin_login_logs(self):
        admin = User.objects.create_superuser(username="log-admin", password="password-123")
        VisitLog.objects.create(
            username=ADMIN_USERNAME,
            log_type="login",
            created_at=1,
            ip="127.0.0.1",
            user_agent="test",
        )
        VisitLog.objects.create(
            username=ADMIN_USERNAME,
            log_type="logout",
            created_at=2,
            ip="127.0.0.1",
            user_agent="test",
        )
        VisitLog.objects.create(
            username="normal-user",
            log_type="login",
            created_at=3,
            ip="127.0.0.1",
            user_agent="test",
        )

        request = self.factory.delete("/0x/user/visit-log")
        force_authenticate(request, user=admin)
        response = VisitLogView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["deleted_count"], 2)
        self.assertEqual(response.data["protected_count"], 1)
        self.assertEqual(VisitLog.objects.count(), 1)
        self.assertTrue(
            VisitLog.objects.filter(username=ADMIN_USERNAME, log_type="login").exists()
        )

    @patch("app.accounts.views.login.TURNSTILE_SECRET_KEY", "test-secret")
    @patch("app.accounts.views.login.TURNSTILE_ENABLED", True)
    @patch("app.accounts.views.login.requests.post")
    def test_turnstile_validation_checks_action(self, post):
        post.return_value.json.return_value = {
            "success": True,
            "action": "login",
        }
        request = self.factory.post(
            "/0x/user/login",
            {"turnstile_token": "test-token"},
            format="json",
        )
        request.data = {"turnstile_token": "test-token"}

        verify_turnstile(request, "login")

        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["data"]["secret"], "test-secret")
        self.assertEqual(post.call_args.kwargs["data"]["response"], "test-token")

    @patch("app.accounts.views.login.TURNSTILE_SECRET_KEY", "test-secret")
    @patch("app.accounts.views.login.TURNSTILE_ENABLED", True)
    @patch("app.accounts.views.login.requests.post")
    def test_turnstile_rejects_wrong_action(self, post):
        post.return_value.json.return_value = {
            "success": True,
            "action": "register",
        }
        request = self.factory.post(
            "/0x/user/login",
            {"turnstile_token": "test-token"},
            format="json",
        )
        request.data = {"turnstile_token": "test-token"}

        with self.assertRaises(ValidationError):
            verify_turnstile(request, "login")
