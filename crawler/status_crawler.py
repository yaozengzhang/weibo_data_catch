from __future__ import annotations

import html as html_lib
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .profile_crawler import parse_count
from .weibo_id import parse_weibo_url


STATUS_COLUMNS = [
    "tweet_id",
    "mid",
    "uid",
    "reported_weibo_url",
    "status_available",
    "unavailable_reason",
    "created_at",
    "text",
    "reposts_count",
    "comments_count",
    "attitudes_count",
    "fetch_status",
    "retrieved_at",
]


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is not None and str(value) != "":
            return str(value)
    return ""


def _count_from_payload(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value))
    return parse_count(value)


def parse_status_payload(payload: dict[str, Any], fallback: dict[str, str] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    status_id = _first_non_empty(payload.get("idstr"), payload.get("id"), fallback.get("tweet_id"))
    mblogid = _first_non_empty(payload.get("mblogid"), fallback.get("mid"))
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}

    return {
        "tweet_id": status_id,
        "id": status_id,
        "idstr": status_id,
        "mid": mblogid,
        "uid": _first_non_empty(user.get("idstr"), user.get("id"), fallback.get("uid")),
        "reported_weibo_url": fallback.get("reported_weibo_url", ""),
        "status_available": "true",
        "unavailable_reason": "",
        "created_at": _first_non_empty(payload.get("created_at"), fallback.get("time")),
        "text": _first_non_empty(payload.get("text_raw"), payload.get("text"), fallback.get("raw")),
        "reposts_count": _count_from_payload(payload.get("reposts_count")),
        "comments_count": _count_from_payload(payload.get("comments_count")),
        "attitudes_count": _count_from_payload(payload.get("attitudes_count")),
        "fetch_status": "ok",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "user": user,
    }


def unavailable_status(fallback: dict[str, str], reason: str, status_available: str = "false") -> dict[str, Any]:
    return {
        "tweet_id": fallback.get("tweet_id", ""),
        "id": fallback.get("tweet_id", ""),
        "idstr": fallback.get("tweet_id", ""),
        "mid": fallback.get("mid", ""),
        "uid": fallback.get("uid", ""),
        "reported_weibo_url": fallback.get("reported_weibo_url", ""),
        "status_available": status_available,
        "unavailable_reason": reason,
        "created_at": "",
        "text": "",
        "reposts_count": "",
        "comments_count": "",
        "attitudes_count": "",
        "fetch_status": reason,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def parse_status_html_fallback(html: str, fallback: dict[str, str] | None = None) -> dict[str, Any]:
    fallback = fallback or {}
    decoded_html = html_lib.unescape(html or "")
    soup = BeautifulSoup(decoded_html, "html.parser")
    body_text = _clean_text(soup.get_text(" ", strip=True))

    result: dict[str, Any] = {
        "tweet_id": fallback.get("tweet_id", ""),
        "id": fallback.get("tweet_id", ""),
        "idstr": fallback.get("tweet_id", ""),
        "mid": fallback.get("mid", ""),
        "uid": fallback.get("uid", ""),
        "reported_weibo_url": fallback.get("reported_weibo_url", ""),
        "status_available": "true",
        "unavailable_reason": "",
        "created_at": fallback.get("time", ""),
        "text": fallback.get("raw", ""),
        "reposts_count": "",
        "comments_count": "",
        "attitudes_count": "",
        "fetch_status": "html_fallback",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }

    if re.search(r"微博不存在|该微博已被删除|内容不存在|暂无查看权限|无法查看|访问的页面不存在", body_text):
        result["status_available"] = "false"
        result["unavailable_reason"] = "deleted_or_unavailable"
        return result

    match = re.search(r"转发\s+((?:\d+(?:\.\d+)?\s*(?:万|亿|w|W|k|K|m|M)?)|评论)\s+((?:\d+(?:\.\d+)?\s*(?:万|亿|w|W|k|K|m|M)?)|赞)\s+分享这条博文", body_text)
    if match:
        result["reposts_count"] = "0"
        result["comments_count"] = "0" if match.group(1) == "评论" else parse_count(match.group(1))
        result["attitudes_count"] = "0" if match.group(2) == "赞" else parse_count(match.group(2))

    return result


class StatusCrawler:
    def __init__(
        self,
        user_data_dir: Path,
        headless: bool = False,
        timeout_ms: int = 30000,
        sleep_ms: int = 1200,
        keep_html: bool = False,
        html_dir: Path | None = None,
        browser_channel: str = "msedge",
        retry_count: int = 2,
        blocked_sleep_seconds: int = 60,
        max_consecutive_blocked: int = 5,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.sleep_ms = sleep_ms
        self.keep_html = keep_html
        self.html_dir = html_dir
        self.browser_channel = browser_channel
        self.retry_count = retry_count
        self.blocked_sleep_seconds = blocked_sleep_seconds
        self.max_consecutive_blocked = max_consecutive_blocked

    def enrich_notices(self, notices: list[dict[str, Any]], limit: int = 0) -> dict[str, dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SystemExit(f"缺少依赖: {exc}. 请先运行 pip install -r requirements.txt") from exc

        targets = self._collect_targets(notices)
        if limit > 0:
            targets = targets[:limit]
        if not targets:
            return {}

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        if self.keep_html and self.html_dir:
            self.html_dir.mkdir(parents=True, exist_ok=True)

        results: dict[str, dict[str, Any]] = {}
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.user_data_dir),
                channel=self.browser_channel or None,
                headless=self.headless,
                viewport={"width": 1365, "height": 900},
                locale="zh-CN",
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(self.timeout_ms)
            consecutive_blocked = 0

            for index, target in enumerate(targets, start=1):
                key = target["key"]
                url = target["reported_weibo_url"]
                print(f"补原微博互动数 {index}/{len(targets)}: {key} {url}")

                payload, request_reason = self._request_status_payload(page, target)
                if payload:
                    results[key] = parse_status_payload(payload, fallback=target)
                    consecutive_blocked = 0
                    time.sleep(self.sleep_ms / 1000)
                    continue
                if request_reason.startswith("blocked_"):
                    results[key] = unavailable_status(target, request_reason, status_available="unknown")
                    consecutive_blocked += 1
                    if consecutive_blocked >= self.max_consecutive_blocked:
                        print(f"连续 {consecutive_blocked} 次触发微博限流，停止继续请求原微博互动数。")
                        for remaining in targets[index:]:
                            results[remaining["key"]] = unavailable_status(
                                remaining,
                                "blocked_stop",
                                status_available="unknown",
                            )
                        break
                    time.sleep(self.sleep_ms / 1000)
                    continue
                if request_reason == "deleted_or_unavailable":
                    results[key] = unavailable_status(target, request_reason)
                    consecutive_blocked = 0
                    time.sleep(self.sleep_ms / 1000)
                    continue

                payload_holder: dict[str, Any] = {}

                def on_response(response: Any) -> None:
                    if "/ajax/statuses/show" not in response.url:
                        return
                    try:
                        payload = response.json()
                    except Exception:
                        return
                    if isinstance(payload, dict) and (payload.get("id") or payload.get("idstr")):
                        payload_holder["payload"] = payload

                page.on("response", on_response)
                try:
                    page.goto(url, wait_until="domcontentloaded")
                    self._wait_for_page(page)
                    page.wait_for_timeout(max(800, self.sleep_ms))
                    payload = payload_holder.get("payload")
                    if payload:
                        parsed = parse_status_payload(payload, fallback=target)
                    else:
                        parsed = parse_status_html_fallback(page.content(), fallback=target)

                    if self.keep_html and self.html_dir:
                        safe_key = re.sub(r"[^0-9A-Za-z_-]+", "_", key) or str(index)
                        (self.html_dir / f"status_{safe_key}.html").write_text(page.content(), encoding="utf-8")

                    results[key] = parsed
                    consecutive_blocked = 0
                except Exception as exc:
                    results[key] = {
                        "tweet_id": target.get("tweet_id", ""),
                        "id": target.get("tweet_id", ""),
                        "idstr": target.get("tweet_id", ""),
                        "mid": target.get("mid", ""),
                        "uid": target.get("uid", ""),
                        "reported_weibo_url": url,
                        "status_available": "unknown",
                        "unavailable_reason": exc.__class__.__name__,
                        "created_at": "",
                        "text": "",
                        "reposts_count": "",
                        "comments_count": "",
                        "attitudes_count": "",
                        "fetch_status": exc.__class__.__name__,
                        "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    }
                finally:
                    page.remove_listener("response", on_response)
                    time.sleep(self.sleep_ms / 1000)

            context.close()
        return results

    def _collect_targets(self, notices: list[dict[str, Any]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        targets: list[dict[str, str]] = []
        for notice in notices:
            url = str(notice.get("reported_weibo_url") or "").strip()
            if not url:
                continue
            parsed = parse_weibo_url(url)
            tweet_id = str(notice.get("tweet_id") or parsed.tweet_id or "").strip()
            mid = str(notice.get("mid") or parsed.mid or "").strip()
            key = tweet_id or mid or url
            if key in seen:
                continue
            seen.add(key)
            targets.append(
                {
                    "key": key,
                    "tweet_id": tweet_id,
                    "mid": mid,
                    "uid": str(notice.get("uid") or notice.get("user_id") or parsed.uid or "").strip(),
                    "time": str(notice.get("time") or "").strip(),
                    "raw": str(notice.get("raw") or "").strip(),
                    "reported_weibo_url": parsed.normalized_url or url,
                }
            )
        return targets

    def _request_status_payload(self, page: Any, target: dict[str, str]) -> tuple[dict[str, Any] | None, str]:
        tweet_id = target.get("tweet_id")
        mid = target.get("mid")

        request_targets: list[tuple[str, str]] = []
        if tweet_id:
            request_targets.append(
                (
                    f"https://m.weibo.cn/statuses/show?id={tweet_id}",
                    f"https://m.weibo.cn/detail/{tweet_id}",
                )
            )
        if mid or tweet_id:
            status_key = mid or tweet_id
            request_targets.append(
                (
                    f"https://weibo.com/ajax/statuses/show?id={status_key}&locale=zh-CN&isGetLongText=true",
                    target.get("reported_weibo_url", "https://weibo.com/"),
                )
            )

        last_reason = "missing_status_id"
        for attempt in range(1, self.retry_count + 1):
            blocked = False
            for request_url, referer in request_targets:
                try:
                    response = page.request.get(
                        request_url,
                        headers={
                            "accept": "application/json, text/plain, */*",
                            "referer": referer,
                            "x-requested-with": "XMLHttpRequest",
                        },
                        timeout=self.timeout_ms,
                    )
                except Exception as exc:
                    last_reason = exc.__class__.__name__
                    continue

                if response.status in {403, 418, 429}:
                    last_reason = f"blocked_{response.status}"
                    blocked = True
                    continue
                if not response.ok:
                    last_reason = f"http_{response.status}"
                    continue

                try:
                    payload = response.json()
                except Exception as exc:
                    last_reason = exc.__class__.__name__
                    continue

                if not isinstance(payload, dict):
                    last_reason = "invalid_payload"
                    continue

                if payload.get("ok") == 1 and isinstance(payload.get("data"), dict):
                    data = payload["data"]
                    if data.get("id") or data.get("idstr"):
                        return data, ""

                if payload.get("id") or payload.get("idstr"):
                    return payload, ""

                message = _clean_text(str(payload.get("msg") or payload.get("message") or payload.get("error") or ""))
                if re.search(r"不存在|已删除|暂无查看权限|无法查看|内容不可见", message):
                    return None, "deleted_or_unavailable"
                last_reason = message or "empty_payload"

            if blocked and attempt < self.retry_count:
                sleep_seconds = self.blocked_sleep_seconds * attempt + random.uniform(1.0, 5.0)
                print(f"  原微博接口触发限流 {last_reason}，等待 {sleep_seconds:.1f}s 后重试。")
                time.sleep(sleep_seconds)
                continue
            break

        return None, last_reason

    def _wait_for_page(self, page: Any) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
