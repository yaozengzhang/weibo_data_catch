from __future__ import annotations

import hashlib
import html as html_lib
import random
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .weibo_id import parse_weibo_url


NOTICE_BASE_URL = "https://service.account.weibo.com/index"
SERVICE_BASE_URL = "https://service.account.weibo.com"


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def build_notice_url(page: int, status: int = 4, notice_type: int = 5) -> str:
    return f"{NOTICE_BASE_URL}?{urlencode({'type': notice_type, 'status': status, 'page': page})}"


def normalize_service_url(url: str) -> str:
    return urljoin(SERVICE_BASE_URL, url or "")


def extract_rid(url: str) -> str:
    parsed = urlparse(normalize_service_url(url))
    query = dict(part.split("=", 1) for part in parsed.query.split("&") if "=" in part)
    return query.get("rid", "")


def extract_report_count(text: str) -> str:
    patterns = [
        r"共\s*(\d+)\s*人举报",
        r"(?:被)?举报(?:次数)?[^\d]{0,10}(\d+)\s*次",
        r"(\d+)\s*次(?:被)?举报",
        r"(?:投诉|举报)[^\d]{0,10}(\d+)\s*(?:人|次)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def extract_time(text: str) -> str:
    patterns = [
        r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?\s+\d{1,2}:\d{2}(?::\d{2})?",
        r"\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}(?:日)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0).replace("年", "-").replace("月", "-").replace("日", "")
    return ""


def parse_date(value: str) -> date | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_date_arg(value: str | None) -> date | None:
    if not value:
        return None
    parsed = parse_date(value)
    if not parsed:
        raise ValueError(f"无法解析日期: {value}")
    return parsed


def extract_raw_text(container: Tag, fallback_text: str) -> str:
    pieces = [clean_text(item) for item in container.stripped_strings]
    pieces = [item for item in pieces if item]

    stop_words = {
        "首页",
        "上一页",
        "下一页",
        "查看",
        "查看原微博",
        "原微博",
        "举报",
        "处理",
        "结果",
        "公示",
    }
    candidates = [
        item
        for item in pieces
        if len(item) >= 6
        and not item.startswith("http")
        and item not in stop_words
        and not re.fullmatch(r"[\d\s:./年月日-]+", item)
    ]

    for marker in ("原微博内容", "微博内容", "被举报微博", "内容"):
        for item in candidates:
            if marker in item:
                value = item.split(marker, 1)[-1].lstrip("：: ")
                return clean_text(value)[:1000]

    if candidates:
        return max(candidates, key=len)[:1000]
    return fallback_text[:1000]


def parse_notice_html(html: str, page_number: int, source_url: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()

    records: list[dict[str, Any]] = []
    seen_record_keys: set[str] = set()

    for row in soup.select("table.m_table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 6:
            continue

        title_link = cells[1].find("a", href=True)
        if not title_link or "show?rid=" not in title_link.get("href", ""):
            continue

        detail_url = normalize_service_url(title_link["href"])
        rid = extract_rid(detail_url)
        reporter_link = cells[2].find("a", href=True)
        reported_link = cells[3].find("a", href=True)
        reported_user_url = reported_link["href"] if reported_link else ""
        parsed_reported = parse_weibo_url(reported_user_url)
        row_text = clean_text(row.get_text(" ", strip=True))

        record_hash = rid or hashlib.sha1(f"{source_url}|{page_number}|{detail_url}|{row_text}".encode("utf-8")).hexdigest()[:16]
        if record_hash in seen_record_keys:
            continue
        seen_record_keys.add(record_hash)

        records.append(
            {
                "notice_id": record_hash,
                "source_page": source_url,
                "page": str(page_number),
                "labels": "不实信息",
                "status_text": clean_text(cells[0].get_text(" ", strip=True)),
                "notice_title": clean_text(title_link.get_text(" ", strip=True)),
                "detail_url": detail_url,
                "rid": rid,
                "time": "",
                "report_time": clean_text(cells[5].get_text(" ", strip=True)),
                "raw": "",
                "reported_weibo_url": "",
                "reporter_user_url": reporter_link["href"] if reporter_link else "",
                "reporter_user_name": clean_text(reporter_link.get_text(" ", strip=True)) if reporter_link else "",
                "reported_user_url": reported_user_url,
                "reported_user_name": clean_text(reported_link.get_text(" ", strip=True)) if reported_link else "",
                "uid": parsed_reported.uid,
                "user_id": parsed_reported.uid,
                "tweet_id": "",
                "mid": "",
                "visit_count": clean_text(cells[4].get_text(" ", strip=True)),
                "report_cnt_explicit": "",
                "decision_text": "",
                "record_text": row_text[:3000],
            }
        )

    return records


def parse_detail_html(html: str, base_record: dict[str, Any] | None = None, detail_url: str = "") -> dict[str, Any]:
    record = dict(base_record or {})
    decoded_html = html_lib.unescape(html or "")
    soup = BeautifulSoup(decoded_html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()

    page_text = clean_text(soup.get_text(" ", strip=True))
    rid_input = soup.find("input", attrs={"node-type": "rid"})
    if rid_input and rid_input.get("value"):
        record["rid"] = str(rid_input["value"])
        record["notice_id"] = record.get("notice_id") or str(rid_input["value"])

    if detail_url:
        record["detail_url"] = detail_url

    title = soup.select_one("h2.m_title")
    if title:
        record["notice_title"] = clean_text(title.get_text(" ", strip=True))

    info = soup.select_one("#pl_content_backCount") or soup.select_one(".m_title.info")
    if info:
        info_text = clean_text(info.get_text(" ", strip=True))
        match = re.search(r"访问次数[:：]\s*(\d+)", info_text)
        if match:
            record["visit_count"] = match.group(1)

    report_count = extract_report_count(page_text)
    if report_count:
        record["report_cnt_explicit"] = report_count

    decision = soup.select_one(".middle_long p.p")
    if decision:
        record["decision_text"] = clean_text(decision.get_text(" ", strip=True))[:3000]

    reporter_area = soup.select_one("[node-type='report_user_area']")
    if reporter_area:
        reporter_link = reporter_area.find("a", href=True)
        if reporter_link:
            record["reporter_user_url"] = reporter_link["href"]
            record["reporter_user_name"] = clean_text(reporter_link.get_text(" ", strip=True))

    reported_info = soup.select_one(".bg_orange2.user")
    if reported_info:
        links = [link for link in reported_info.find_all("a", href=True) if "weibo.com" in link["href"]]
        if links:
            record["reported_user_url"] = links[0]["href"]
            record["reported_user_name"] = clean_text(links[0].get_text(" ", strip=True))
            parsed_user = parse_weibo_url(links[0]["href"])
            if parsed_user.uid:
                record["uid"] = parsed_user.uid
                record["user_id"] = parsed_user.uid
        profile_lines = [clean_text(item.get_text(" ", strip=True)) for item in reported_info.find_all("p")]
        profile_lines = [line for line in profile_lines if line and line != "\xa0"]
        if len(profile_lines) >= 3:
            record["des"] = profile_lines[-1]

    original_link = None
    for link in soup.find_all("a", href=True):
        if clean_text(link.get_text(" ", strip=True)) == "原文" and "weibo.com" in link["href"]:
            original_link = link
            break

    if original_link:
        parsed_status = parse_weibo_url(original_link["href"])
        record["reported_weibo_url"] = parsed_status.normalized_url
        record["tweet_id"] = parsed_status.tweet_id
        record["mid"] = parsed_status.mid
        if parsed_status.uid:
            record["uid"] = parsed_status.uid
            record["user_id"] = parsed_status.uid

    publisher_text = ""
    if original_link:
        publisher = original_link.find_parent("p", class_="publisher")
        if publisher:
            publisher_text = clean_text(publisher.get_text(" ", strip=True))
    original_time = extract_time(publisher_text)
    if original_time:
        record["time"] = original_time

    raw_input = soup.find("input", attrs={"node-type": "right_top"})
    if raw_input and raw_input.get("value"):
        record["raw"] = clean_text(str(raw_input["value"]))
    else:
        right_feed = soup.select_one("[node-type='feedsrightArea'] .feed .con")
        if right_feed:
            record["raw"] = extract_raw_text(right_feed, clean_text(right_feed.get_text(" ", strip=True)))

    record["record_text"] = page_text[:3000]
    return record


class NoticeCrawler:
    def __init__(
        self,
        user_data_dir: Path,
        headless: bool = False,
        timeout_ms: int = 30000,
        keep_html: bool = False,
        html_dir: Path | None = None,
        browser_channel: str = "msedge",
        page_sleep_ms: int = 1500,
        detail_sleep_ms: int = 800,
        retry_count: int = 3,
        blocked_sleep_seconds: int = 120,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.keep_html = keep_html
        self.html_dir = html_dir
        self.browser_channel = browser_channel
        self.page_sleep_ms = page_sleep_ms
        self.detail_sleep_ms = detail_sleep_ms
        self.retry_count = retry_count
        self.blocked_sleep_seconds = blocked_sleep_seconds

    def crawl(
        self,
        start_page: int,
        end_page: int,
        status: int = 4,
        notice_type: int = 5,
        login: bool = False,
        require_original_link: bool = False,
        date_from: date | None = None,
        date_to: date | None = None,
        stop_before_date: bool = True,
        on_page_records: Callable[[int, list[dict[str, Any]], dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SystemExit(f"缺少依赖: {exc}. 请先运行 pip install -r requirements.txt") from exc

        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        if self.keep_html and self.html_dir:
            self.html_dir.mkdir(parents=True, exist_ok=True)

        all_records: list[dict[str, Any]] = []
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

            first_url = build_notice_url(start_page, status=status, notice_type=notice_type)
            self._goto_with_retries(page, first_url, "初始列表页")
            self._wait_for_page(page)

            if login or "login" in page.url:
                print("\n需要登录微博：")
                print("1. 在弹出的浏览器窗口完成微博登录。")
                print("2. 登录后手动打开或保持在社区管理中心不实信息页面。")
                print("3. 回到这个终端按 Enter，脚本会继续抓取。\n")
                input("登录完成后按 Enter 继续...")

            for page_number in range(start_page, end_page + 1):
                target_url = build_notice_url(page_number, status=status, notice_type=notice_type)
                print(f"抓取页面: {target_url}")
                self._goto_with_retries(page, target_url, f"列表页 {page_number}")
                self._wait_for_page(page)
                self._scroll_to_bottom(page)

                html = page.content()
                if self.keep_html and self.html_dir:
                    html_path = self.html_dir / f"notice_status{status}_page{page_number}.html"
                    html_path.write_text(html, encoding="utf-8")

                records = parse_notice_html(html, page_number=page_number, source_url=target_url)
                print(f"  解析到 {len(records)} 条列表记录")
                page_records: list[dict[str, Any]] = []
                page_stats: dict[str, Any] = {
                    "source_page": target_url,
                    "list_count": len(records),
                    "detail_count": 0,
                    "kept_count": 0,
                    "skipped_newer": 0,
                    "skipped_older": 0,
                    "skipped_no_original": 0,
                    "skipped_unknown_date": 0,
                    "stop_after_page": False,
                }
                detail_records: list[dict[str, Any]] = []
                for record in records:
                    report_date = parse_date(str(record.get("report_time") or ""))
                    if (date_from or date_to) and not report_date:
                        page_stats["skipped_unknown_date"] += 1
                        continue
                    if date_to and report_date and report_date > date_to:
                        page_stats["skipped_newer"] += 1
                        continue
                    if date_from and report_date and report_date < date_from:
                        page_stats["skipped_older"] += 1
                        if stop_before_date:
                            page_stats["stop_after_page"] = True
                        continue
                    detail_records.append(record)

                if date_from or date_to:
                    print(
                        "  日期过滤后待抓详情 "
                        f"{len(detail_records)} 条；跳过较新 {page_stats['skipped_newer']}，"
                        f"跳过较旧 {page_stats['skipped_older']}"
                    )

                for index, record in enumerate(detail_records, start=1):
                    detail_url = record.get("detail_url")
                    if not detail_url:
                        if not require_original_link:
                            all_records.append(record)
                            page_records.append(record)
                        continue
                    print(f"  抓取详情 {index}/{len(detail_records)}: {detail_url}")
                    self._goto_with_retries(page, str(detail_url), f"详情页 {record.get('rid') or index}")
                    self._wait_for_page(page)
                    self._scroll_to_bottom(page)
                    detail_html = page.content()
                    if self.keep_html and self.html_dir:
                        rid = record.get("rid") or str(index)
                        detail_path = self.html_dir / f"detail_{rid}.html"
                        detail_path.write_text(detail_html, encoding="utf-8")
                    parsed_record = parse_detail_html(detail_html, base_record=record, detail_url=str(detail_url))
                    if require_original_link and not (
                        parsed_record.get("reported_weibo_url") and parsed_record.get("tweet_id")
                    ):
                        print(f"  跳过无原文按钮记录: {parsed_record.get('rid') or detail_url}")
                        page_stats["skipped_no_original"] += 1
                        continue
                    all_records.append(parsed_record)
                    page_records.append(parsed_record)
                    page_stats["detail_count"] += 1
                    page_stats["kept_count"] += 1
                    time.sleep(self.detail_sleep_ms / 1000)

                if on_page_records:
                    on_page_records(page_number, page_records, page_stats)
                time.sleep(self.page_sleep_ms / 1000)
                if page_stats["stop_after_page"]:
                    print(f"  已到达早于 {date_from} 的记录，停止继续翻页。")
                    break

            context.close()
        return all_records

    def _goto_with_retries(self, page: Any, url: str, label: str) -> None:
        last_error: Exception | None = None
        for attempt in range(1, self.retry_count + 1):
            try:
                page.goto(url, wait_until="domcontentloaded")
                return
            except Exception as exc:
                last_error = exc
                message = str(exc)
                blocked = any(code in message for code in ("403", "418", "429", "ERR_HTTP_RESPONSE_CODE_FAILURE"))
                sleep_seconds = self.blocked_sleep_seconds if blocked else min(30, 2**attempt)
                sleep_seconds += random.uniform(0.5, 3.0)
                print(f"  {label} 打开失败，第 {attempt}/{self.retry_count} 次: {exc.__class__.__name__}; 等待 {sleep_seconds:.1f}s")
                if attempt < self.retry_count:
                    time.sleep(sleep_seconds)
        if last_error:
            raise last_error

    def _wait_for_page(self, page: Any) -> None:
        try:
            page.wait_for_load_state("networkidle", timeout=self.timeout_ms)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise

    def _scroll_to_bottom(self, page: Any) -> None:
        try:
            previous_height = 0
            for _ in range(4):
                height = page.evaluate("document.body.scrollHeight")
                if height == previous_height:
                    break
                previous_height = height
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
