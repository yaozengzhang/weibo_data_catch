from __future__ import annotations

import html as html_lib
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup


PROFILE_COLUMNS = [
    "uid",
    "followers_count",
    "friends_count",
    "statuses_count",
    "favourites_count",
    "bi_followers_count",
    "credit_score",
    "verified",
    "des",
    "profile_url",
]

PROFILE_FAILURE_COLUMNS = [
    "uid",
    "profile_url",
    "error",
    "retrieved_at",
]


def parse_count(value: Any) -> str:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return ""

    unit = 1
    lowered = text.lower()
    if "亿" in text:
        unit = 100000000
    elif "万" in text or "w" in lowered:
        unit = 10000
    elif "k" in lowered:
        unit = 1000
    elif "m" in lowered:
        unit = 1000000

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return ""
    number = float(match.group(0)) * unit
    return str(int(number))


def _profile_name(soup: BeautifulSoup) -> str:
    if soup.title:
        match = re.search(r"@(.+?)\s+的个人主页", soup.title.get_text(" ", strip=True))
        if match:
            return match.group(1).strip()
    return ""


def _visible_profile_fields(body_text: str, profile_name: str) -> dict[str, str]:
    number = r"([0-9][0-9,.]*(?:\.\d+)?\s*(?:万|亿|w|W|k|K|m|M)?)"
    fields = {
        "followers_count": "",
        "friends_count": "",
        "statuses_count": "",
        "des": "",
    }

    if profile_name:
        escaped_name = re.escape(profile_name)
        match = re.search(
            rf"{escaped_name}\s+{number}\s+粉丝\s+{number}\s+关注\s+{number}\s+转评赞",
            body_text,
        )
        if match:
            fields["followers_count"] = parse_count(match.group(1))
            fields["friends_count"] = parse_count(match.group(2))

        desc_match = re.search(
            rf"{escaped_name}\s+{number}\s+粉丝\s+{number}\s+关注\s+{number}\s+转评赞\s+关注\s+留言\s+(?:视频累计播放量\d+\s+)?(.+?)\s+IP属地[:：]",
            body_text,
        )
        if desc_match:
            fields["des"] = desc_match.group(4).strip()

    status_match = re.search(r"全部微博[（(]\s*([0-9][0-9,]*)\s*[）)]", body_text)
    if status_match:
        fields["statuses_count"] = parse_count(status_match.group(1))

    return fields


def parse_profile_html(html: str, uid: str = "", profile_url: str = "") -> dict[str, str]:
    decoded_html = html_lib.unescape(html or "")
    soup = BeautifulSoup(decoded_html, "html.parser")
    body_text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    profile_name = _profile_name(soup)

    visible = _visible_profile_fields(body_text, profile_name)
    verified = "true" if re.search(r"微博认证|认证用户|已认证", body_text) else ""

    return {
        "uid": uid,
        "followers_count": visible["followers_count"],
        "friends_count": visible["friends_count"],
        "statuses_count": visible["statuses_count"],
        "favourites_count": "",
        "bi_followers_count": "",
        "credit_score": "",
        "verified": verified,
        "des": visible["des"],
        "profile_url": profile_url,
    }


class ProfileCrawler:
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
        self.failures: list[dict[str, str]] = []

    def enrich_notices(self, notices: list[dict[str, Any]], limit: int = 0) -> dict[str, dict[str, str]]:
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

        results: dict[str, dict[str, str]] = {}
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

            for index, target in enumerate(targets, start=1):
                uid = target["uid"]
                url = target["url"]
                print(f"补用户主页字段 {index}/{len(targets)}: {uid} {url}")
                try:
                    self._goto_with_retries(page, url, f"用户主页 {uid}")
                    self._wait_for_page(page)
                    self._scroll_once(page)
                    html = page.content()

                    if self.keep_html and self.html_dir:
                        safe_uid = uid or str(index)
                        (self.html_dir / f"profile_{safe_uid}.html").write_text(html, encoding="utf-8")

                    parsed = parse_profile_html(html, uid=uid, profile_url=url)
                    results[uid] = parsed
                except Exception as exc:
                    print(f"  用户主页失败，已跳过: {uid} {exc.__class__.__name__}")
                    self.failures.append(
                        {
                            "uid": uid,
                            "profile_url": url,
                            "error": exc.__class__.__name__,
                            "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        }
                    )
                time.sleep(self.sleep_ms / 1000)

            context.close()
        return results

    def _collect_targets(self, notices: list[dict[str, Any]]) -> list[dict[str, str]]:
        seen: set[str] = set()
        targets: list[dict[str, str]] = []
        for notice in notices:
            uid = str(notice.get("uid") or notice.get("user_id") or "").strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            url = str(notice.get("reported_user_url") or "").strip()
            if not url:
                url = f"https://m.weibo.cn/u/{uid}"
            targets.append({"uid": uid, "url": url})
        return targets

    def _wait_for_page(self, page: Any) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise

    def _goto_with_retries(self, page: Any, url: str, label: str) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.retry_count + 1):
            try:
                page.goto(url, wait_until="domcontentloaded")
                return
            except Exception as exc:
                last_error = exc
                blocked = any(code in str(exc) for code in ("403", "418", "429", "ERR_HTTP_RESPONSE_CODE_FAILURE"))
                sleep_seconds = self.blocked_sleep_seconds if blocked else min(30, 2**attempt)
                sleep_seconds += random.uniform(0.5, 3.0)
                print(f"  {label} 打开失败，第 {attempt}/{self.retry_count} 次: {exc.__class__.__name__}; 等待 {sleep_seconds:.1f}s")
                if attempt < self.retry_count:
                    time.sleep(sleep_seconds)
        if last_error:
            raise last_error

    def _scroll_once(self, page: Any) -> None:
        try:
            page.evaluate("window.scrollTo(0, Math.min(document.body.scrollHeight, 1200))")
            page.wait_for_timeout(800)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
