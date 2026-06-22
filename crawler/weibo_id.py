from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse


WEIBO_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class ParsedWeiboUrl:
    raw_url: str
    normalized_url: str
    uid: str = ""
    tweet_id: str = ""
    mid: str = ""

    @property
    def is_status(self) -> bool:
        return bool(self.tweet_id or self.mid)

    @property
    def is_user(self) -> bool:
        return bool(self.uid) and not self.is_status


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return "https://weibo.com" + url
    return url


def base62_decode(value: str) -> int:
    total = 0
    for char in value:
        total = total * 62 + WEIBO_BASE62.index(char)
    return total


def mid_to_id(mid: str) -> str:
    """Convert a Weibo base62 mid from URL form to the numeric status id."""
    mid = (mid or "").strip()
    if not mid:
        return ""

    parts = []
    while mid:
        parts.insert(0, mid[-4:])
        mid = mid[:-4]

    decoded = []
    for index, part in enumerate(parts):
        number = str(base62_decode(part))
        if index > 0:
            number = number.zfill(7)
        decoded.append(number)
    return "".join(decoded)


def id_to_mid(status_id: str) -> str:
    """Convert a numeric Weibo status id to URL base62 form."""
    status_id = str(status_id or "").strip()
    if not status_id.isdigit():
        return ""

    parts = []
    while status_id:
        parts.insert(0, status_id[-7:])
        status_id = status_id[:-7]

    encoded = []
    for part in parts:
        number = int(part)
        chars = []
        if number == 0:
            chars.append("0")
        while number:
            number, remainder = divmod(number, 62)
            chars.insert(0, WEIBO_BASE62[remainder])
        encoded.append("".join(chars))
    return "".join(encoded)


def parse_weibo_url(url: str) -> ParsedWeiboUrl:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    host = parsed.netloc.lower()
    path_parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)

    uid = ""
    tweet_id = ""
    mid = ""

    if "weibo.com" not in host and "weibo.cn" not in host:
        return ParsedWeiboUrl(url, normalized)

    if "m.weibo.cn" in host:
        if len(path_parts) >= 2 and path_parts[0] in {"status", "detail"}:
            tweet_id = path_parts[1]
        elif len(path_parts) >= 2 and path_parts[0] == "profile":
            uid = path_parts[1]
        elif len(path_parts) >= 2 and path_parts[0] == "u":
            uid = path_parts[1]
    else:
        if len(path_parts) >= 2 and path_parts[0] == "u":
            uid = path_parts[1]
        elif len(path_parts) >= 2 and path_parts[0].isdigit():
            uid = path_parts[0]
            candidate = path_parts[1]
            if candidate in {"home", "profile", "info"}:
                pass
            elif candidate.isdigit():
                tweet_id = candidate
                mid = id_to_mid(candidate)
            else:
                mid = candidate
                try:
                    tweet_id = mid_to_id(candidate)
                except ValueError:
                    tweet_id = ""
                    mid = ""
        elif len(path_parts) == 1 and path_parts[0].isdigit():
            uid = path_parts[0]

    for key in ("mid", "mblogid"):
        if not mid and query.get(key):
            mid = query[key][0]
            if mid.isdigit():
                tweet_id = mid
                mid = id_to_mid(mid)
            else:
                try:
                    tweet_id = mid_to_id(mid)
                except ValueError:
                    tweet_id = ""
                    mid = ""

    if not tweet_id and query.get("id"):
        candidate = query["id"][0]
        if candidate.isdigit():
            tweet_id = candidate
            mid = id_to_mid(candidate)

    return ParsedWeiboUrl(url, normalized, uid=uid, tweet_id=tweet_id, mid=mid)


def first_status_url(urls: list[str]) -> Optional[ParsedWeiboUrl]:
    for url in urls:
        parsed = parse_weibo_url(url)
        if parsed.is_status:
            return parsed
    return None
