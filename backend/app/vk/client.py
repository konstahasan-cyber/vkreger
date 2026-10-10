"""Thin synchronous client for the official VK API (https://dev.vk.com/ru/method).

* The access token is sent in the POST body, never in the URL, so it can't leak into
  proxy/server access logs or our own logs.
* Requests go through the proxy bound to the account (if any).
* Error 6 (too many requests per second) is retried with back-off.  Captcha (14) and
  flood control (9) are *not* worked around — they're raised to the caller, which
  stops the task and records the error.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any

import httpx

from app.core.config import settings
from app.vk.errors import VKAPIError, VKNetworkError

logger = logging.getLogger(__name__)

_last_call: dict[int, float] = {}
_lock = threading.Lock()


def _throttle(token: str) -> None:
    key = hash(token)
    with _lock:
        now = time.monotonic()
        wait = _last_call.get(key, 0.0) + settings.VK_MIN_REQUEST_INTERVAL - now
        _last_call[key] = max(now, now + wait)
    if wait > 0:
        time.sleep(wait)


class VKClient:
    def __init__(
        self,
        token: str,
        *,
        proxy_url: str | None = None,
        api_version: str | None = None,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        self._token = token
        self.api_version = api_version or settings.VK_API_VERSION
        self._http = httpx.Client(
            proxy=proxy_url if transport is None else None,
            transport=transport,
            timeout=timeout or settings.VK_REQUEST_TIMEOUT,
        )

    def __repr__(self) -> str:
        return f"<VKClient v={self.api_version}>"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> VKClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def call(self, method: str, **params: Any) -> Any:
        data = {k: self._serialize(v) for k, v in params.items() if v is not None}
        data["access_token"] = self._token
        data["v"] = self.api_version
        attempts = 0
        while True:
            attempts += 1
            _throttle(self._token)
            try:
                response = self._http.post(f"{settings.VK_API_BASE_URL}/{method}", data=data)
            except httpx.HTTPError as exc:
                raise VKNetworkError(f"{method}: {type(exc).__name__}") from exc
            if response.status_code >= 500:
                raise VKNetworkError(f"{method}: HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError:
                # e.g. an HTML error page from a proxy (407/403) — treat as a network problem
                raise VKNetworkError(f"{method}: non-JSON response (HTTP {response.status_code})") from None
            if "error" in payload:
                err = payload["error"]
                exc = VKAPIError(
                    int(err.get("error_code", 0)),
                    str(err.get("error_msg", "")),
                    method,
                    {k: v for k, v in err.items() if k not in ("request_params",)},
                )
                if exc.code == 6 and attempts < 4:
                    time.sleep(0.5 * attempts)
                    continue
                logger.warning("VK %s failed: code=%s %s", method, exc.code, exc.message)
                raise exc
            if "execute_errors" in payload:
                logger.warning("VK execute errors in %s: %s", method, payload["execute_errors"])
            return payload.get("response")

    @staticmethod
    def _serialize(value: Any) -> Any:
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (list, tuple, set)):
            return ",".join(str(v) for v in value)
        return value

    def upload(self, upload_url: str, field: str, filename: str, content: bytes, mime: str = "image/jpeg") -> dict:
        try:
            response = self._http.post(upload_url, files={field: (filename, content, mime)})
        except httpx.HTTPError as exc:
            raise VKNetworkError(f"upload: {type(exc).__name__}") from exc
        try:
            data = response.json()
        except ValueError:
            raise VKNetworkError(f"upload: non-JSON response (HTTP {response.status_code})") from None
        if "error" in data:
            raise VKAPIError(0, str(data["error"]), "upload")
        return data

    def raw_get(self, url: str, params: dict[str, Any], timeout: float | None = None) -> dict:
        try:
            response = self._http.get(url, params=params, timeout=timeout)
        except httpx.HTTPError as exc:
            raise VKNetworkError(f"GET {type(exc).__name__}") from exc
        try:
            return response.json()
        except ValueError:
            raise VKNetworkError(f"GET: non-JSON response (HTTP {response.status_code})") from None

    # ------------------------------------------------------------- users
    def get_current_user(self) -> dict:
        users = self.call("users.get", fields="photo_100,screen_name")
        if not users:
            raise VKAPIError(5, "users.get returned no user (community token?)", "users.get")
        return users[0]

    def get_app_permissions(self) -> int | None:
        try:
            return int(self.call("account.getAppPermissions"))
        except VKAPIError:
            return None

    # ------------------------------------------------------------- groups
    def get_admin_groups(self) -> list[dict]:
        resp = self.call("groups.get", filter="admin", extended=1, fields="members_count,description,screen_name", count=1000)
        return resp.get("items", []) if resp else []

    def get_group(self, group_id: int | str | None = None) -> dict:
        """With a community key and no ID VK returns the key's own community."""
        resp = self.call("groups.getById", group_id=group_id, fields="members_count,description,status,site,can_post")
        # 5.199 returns {"groups": [...], "profiles": [...]}; older versions — a list.
        groups = resp.get("groups", []) if isinstance(resp, dict) else resp
        if not groups:
            raise VKAPIError(100, "group not found", "groups.getById")
        return groups[0]

    def create_group(self, title: str, description: str | None = None, *, type_: str = "public",
                     public_category: int | None = None, subtype: int | None = None) -> dict:
        return self.call(
            "groups.create", title=title, description=description, type=type_,
            public_category=public_category, subtype=subtype,
        )

    def edit_group(self, group_id: int, **fields: Any) -> Any:
        return self.call("groups.edit", group_id=group_id, **fields)

    def set_status(self, group_id: int, text: str) -> Any:
        return self.call("status.set", group_id=group_id, text=text)

    # ------------------------------------------------------------- wall
    def wall_post(self, group_id: int, message: str, *, attachments: list[str] | None = None,
                  guid: str | None = None, publish_date: int | None = None) -> int:
        resp = self.call(
            "wall.post", owner_id=-abs(group_id), from_group=1, message=message,
            attachments=attachments or None, guid=guid, publish_date=publish_date,
        )
        return int(resp["post_id"])

    def wall_pin(self, group_id: int, post_id: int) -> Any:
        return self.call("wall.pin", owner_id=-abs(group_id), post_id=post_id)

    def wall_get(self, group_id: int, count: int = 20) -> list[dict]:
        resp = self.call("wall.get", owner_id=-abs(group_id), count=count)
        return resp.get("items", []) if resp else []

    def wall_get_by_id(self, group_id: int, post_ids: list[int]) -> list[dict]:
        posts = ",".join(f"-{abs(group_id)}_{pid}" for pid in post_ids)
        resp = self.call("wall.getById", posts=posts)
        return resp.get("items", []) if isinstance(resp, dict) else (resp or [])

    def post_reach(self, group_id: int, post_ids: list[int]) -> list[dict]:
        return self.call("stats.getPostReach", owner_id=-abs(group_id), post_ids=post_ids) or []

    def create_comment(self, group_id: int, post_id: int, message: str, reply_to_comment: int | None = None) -> int:
        resp = self.call(
            "wall.createComment", owner_id=-abs(group_id), post_id=post_id, from_group=abs(group_id),
            message=message, reply_to_comment=reply_to_comment,
        )
        return int(resp["comment_id"])

    # ------------------------------------------------------------- messages (community token)
    def send_message(self, peer_id: int, message: str, group_id: int | None = None) -> int:
        resp = self.call(
            "messages.send", peer_id=peer_id, message=message, random_id=random.randint(1, 2**31 - 1),
            group_id=group_id,
        )
        return int(resp) if not isinstance(resp, list) else int(resp[0].get("message_id", 0))

    # ------------------------------------------------------------- photos
    def upload_wall_photo(self, group_id: int, content: bytes, filename: str = "image.png") -> str:
        server = self.call("photos.getWallUploadServer", group_id=abs(group_id))
        uploaded = self.upload(server["upload_url"], "photo", filename, content, "image/png")
        saved = self.call(
            "photos.saveWallPhoto", group_id=abs(group_id), photo=uploaded["photo"],
            server=uploaded["server"], hash=uploaded["hash"],
        )
        photo = saved[0]
        return f"photo{photo['owner_id']}_{photo['id']}"

    def upload_cover(self, group_id: int, content: bytes, width: int, height: int) -> Any:
        server = self.call(
            "photos.getOwnerCoverPhotoUploadServer", group_id=abs(group_id),
            crop_x=0, crop_y=0, crop_x2=width, crop_y2=height,
        )
        uploaded = self.upload(server["upload_url"], "photo", "cover.png", content, "image/png")
        return self.call("photos.saveOwnerCoverPhoto", hash=uploaded["hash"], photo=uploaded["photo"])

    def upload_group_avatar(self, group_id: int, content: bytes) -> Any:
        server = self.call("photos.getOwnerPhotoUploadServer", owner_id=-abs(group_id))
        uploaded = self.upload(server["upload_url"], "photo", "avatar.png", content, "image/png")
        return self.call("photos.saveOwnerPhoto", server=uploaded["server"], hash=uploaded["hash"], photo=uploaded["photo"])

    # ------------------------------------------------------------- events
    def get_callback_confirmation_code(self, group_id: int) -> str:
        return self.call("groups.getCallbackConfirmationCode", group_id=abs(group_id))["code"]

    def add_callback_server(self, group_id: int, url: str, title: str, secret_key: str) -> int:
        return int(self.call("groups.addCallbackServer", group_id=abs(group_id), url=url, title=title[:14],
                             secret_key=secret_key)["server_id"])

    def set_callback_settings(self, group_id: int, server_id: int) -> Any:
        return self.call(
            "groups.setCallbackSettings", group_id=abs(group_id), server_id=server_id,
            api_version=self.api_version, message_new=1, wall_reply_new=1, wall_post_new=0,
        )

    def set_long_poll_settings(self, group_id: int) -> Any:
        return self.call(
            "groups.setLongPollSettings", group_id=abs(group_id), enabled=1,
            api_version=self.api_version, message_new=1, wall_reply_new=1,
        )

    def get_long_poll_server(self, group_id: int) -> dict:
        return self.call("groups.getLongPollServer", group_id=abs(group_id))
