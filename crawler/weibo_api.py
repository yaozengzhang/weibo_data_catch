from __future__ import annotations

import time
from typing import Any, Optional

import requests


class WeiboAPI:
    def __init__(self, access_token: str, sleep_seconds: float = 1.0, timeout: int = 20):
        self.access_token = access_token
        self.sleep_seconds = sleep_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.last_error = ""

    def _get(self, url: str, params: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self.access_token:
            return None

        payload = dict(params)
        payload["access_token"] = self.access_token
        time.sleep(self.sleep_seconds)

        try:
            response = self.session.get(url, params=payload, timeout=self.timeout)
            if response.status_code != 200:
                self.last_error = f"{response.status_code}: {response.text[:300]}"
                return None
            data = response.json()
            if isinstance(data, dict) and data.get("error"):
                self.last_error = str(data)
                return None
            return data if isinstance(data, dict) else None
        except requests.RequestException as exc:
            self.last_error = str(exc)
            return None
        except ValueError as exc:
            self.last_error = f"JSON parse error: {exc}"
            return None

    def status_show(self, status_id: str) -> Optional[dict[str, Any]]:
        return self._get(
            "https://api.weibo.com/2/statuses/show.json",
            {"id": status_id},
        )

    def user_show(self, uid: str = "", screen_name: str = "") -> Optional[dict[str, Any]]:
        params: dict[str, Any]
        if uid:
            params = {"uid": uid}
        elif screen_name:
            params = {"screen_name": screen_name}
        else:
            return None
        return self._get("https://api.weibo.com/2/users/show.json", params)

    def comments_show(self, status_id: str, page: int = 1, count: int = 50) -> Optional[dict[str, Any]]:
        return self._get(
            "https://api.weibo.com/2/comments/show.json",
            {"id": status_id, "page": page, "count": count},
        )

    def comment_like_sum(self, status_id: str, max_pages: int = 1) -> str:
        if max_pages <= 0:
            return ""

        total = 0
        saw_like_field = False
        for page in range(1, max_pages + 1):
            data = self.comments_show(status_id, page=page)
            if not data:
                break
            comments = data.get("comments") or []
            if not comments:
                break
            for comment in comments:
                for key in ("like_counts", "like_count", "likes_count"):
                    if key in comment:
                        saw_like_field = True
                        try:
                            total += int(comment.get(key) or 0)
                        except (TypeError, ValueError):
                            pass
                        break
        return str(total) if saw_like_field else ""
