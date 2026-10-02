"""In-memory imitation of the VK API used by tests (httpx.MockTransport)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs

import httpx

VALID_USER_TOKEN = "vk1.a.user-token-ok"
COMMUNITY_TOKEN = "vk1.a.community-token"


class FakeVK:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.groups: dict[int, dict] = {
            101: {"id": 101, "name": "Existing Group", "screen_name": "club101", "is_admin": 1, "members_count": 50},
        }
        self.walls: dict[int, list[dict]] = {}
        self.guids: dict[str, int] = {}
        self.next_group_id = 500
        self.next_post_id = 1
        self.fail_next: dict[str, list[dict]] = {}  # method -> queue of errors to return
        self.comments: list[dict] = []
        self.messages: list[dict] = []
        self.pinned: dict[int, int] = {}
        self.uploads = 0

    def fail(self, method: str, code: int, msg: str = "error", times: int = 1) -> None:
        self.fail_next.setdefault(method, []).extend([{"error_code": code, "error_msg": msg}] * times)

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "upload.vk.test":
            self.uploads += 1
            return httpx.Response(200, json={"server": 1, "photo": "[]", "hash": "h"})
        if request.url.host == "lp.vk.test":
            return httpx.Response(200, json={"ts": "2", "updates": []})
        method = request.url.path.rsplit("/", 1)[-1]
        params = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        self.calls.append((method, params))
        assert "access_token" not in str(request.url), "token must not be sent in URL"
        if self.fail_next.get(method):
            return httpx.Response(200, json={"error": self.fail_next[method].pop(0)})
        token = params.get("access_token")
        if token not in (VALID_USER_TOKEN, COMMUNITY_TOKEN):
            return httpx.Response(200, json={"error": {"error_code": 5, "error_msg": "User authorization failed"}})
        handler = getattr(self, "m_" + method.replace(".", "_"), None)
        if handler is None:
            return httpx.Response(200, json={"response": 1})
        return httpx.Response(200, json={"response": handler(params)})

    # ---- methods
    def m_users_get(self, p: dict) -> list:
        return [{"id": 1, "first_name": "Ivan", "last_name": "Petrov", "screen_name": "ivan"}]

    def m_account_getAppPermissions(self, p: dict) -> int:
        return 140492255

    def m_groups_get(self, p: dict) -> dict:
        return {"count": len(self.groups), "items": list(self.groups.values())}

    def m_groups_getById(self, p: dict) -> dict:
        gid = int(p["group_id"])
        return {"groups": [self.groups[gid]], "profiles": []}

    def m_groups_create(self, p: dict) -> dict:
        gid = self.next_group_id
        self.next_group_id += 1
        self.groups[gid] = {"id": gid, "name": p["title"], "screen_name": f"public{gid}", "is_admin": 1,
                            "members_count": 1, "description": p.get("description")}
        return {"id": gid, "name": p["title"], "type": p.get("type")}

    def m_groups_edit(self, p: dict) -> int:
        group = self.groups[int(p["group_id"])]
        group.update({k: v for k, v in p.items() if k in ("title", "description", "website")})
        return 1

    def m_wall_post(self, p: dict) -> dict:
        guid = p.get("guid")
        if guid and guid in self.guids:
            return {"post_id": self.guids[guid]}
        pid = self.next_post_id
        self.next_post_id += 1
        owner = int(p["owner_id"])
        self.walls.setdefault(owner, []).insert(0, {"id": pid, "text": p.get("message", ""),
                                                    "attachments": p.get("attachments")})
        if guid:
            self.guids[guid] = pid
        return {"post_id": pid}

    def m_wall_get(self, p: dict) -> dict:
        items = self.walls.get(int(p["owner_id"]), [])
        return {"count": len(items), "items": items[: int(p.get("count", 20))]}

    def m_wall_pin(self, p: dict) -> int:
        self.pinned[int(p["owner_id"])] = int(p["post_id"])
        return 1

    def m_wall_getById(self, p: dict) -> dict:
        items = []
        for ref in p["posts"].split(","):
            _, pid = ref.split("_")
            pid = int(pid)
            items.append({"id": pid, "views": {"count": 100 * pid}, "likes": {"count": 5 * pid},
                          "comments": {"count": pid}, "reposts": {"count": 1}})
        return {"items": items}

    def m_stats_getPostReach(self, p: dict) -> list:
        return [{"post_id": int(pid), "reach_total": 90, "links": 3} for pid in p["post_ids"].split(",")]

    def m_photos_getWallUploadServer(self, p: dict) -> dict:
        return {"upload_url": "https://upload.vk.test/upload"}

    def m_photos_saveWallPhoto(self, p: dict) -> list:
        return [{"id": 777, "owner_id": -int(p["group_id"])}]

    def m_wall_createComment(self, p: dict) -> dict:
        self.comments.append(p)
        return {"comment_id": 900 + len(self.comments)}

    def m_messages_send(self, p: dict) -> int:
        self.messages.append(p)
        return 5000 + len(self.messages)

    def m_groups_getCallbackConfirmationCode(self, p: dict) -> dict:
        return {"code": "abc123"}

    def m_groups_addCallbackServer(self, p: dict) -> dict:
        return {"server_id": 3}

    def m_groups_getLongPollServer(self, p: dict) -> dict:
        return {"server": "https://lp.vk.test/poll", "key": "k", "ts": "1"}


def dumps(obj: object) -> str:
    return json.dumps(obj)
