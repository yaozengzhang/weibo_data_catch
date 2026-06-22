from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

from .weibo_api import WeiboAPI


NOTICE_COLUMNS = [
    "notice_id",
    "source_page",
    "page",
    "labels",
    "status_text",
    "notice_title",
    "detail_url",
    "rid",
    "time",
    "report_time",
    "raw",
    "reported_weibo_url",
    "reporter_user_url",
    "reporter_user_name",
    "reported_user_url",
    "reported_user_name",
    "des",
    "uid",
    "user_id",
    "tweet_id",
    "mid",
    "visit_count",
    "report_cnt_explicit",
    "decision_text",
    "record_text",
]

DATASET_COLUMNS = [
    "uid",
    "labels",
    "time",
    "raw",
    "favourites_count",
    "statuses_count",
    "friends_count",
    "followers_count",
    "bi_followers_count",
    "credit_score",
    "verified",
    "comment_cnt",
    "comment_like_cnt",
    "like_cnt",
    "repost_cnt",
    "report_cnt",
    "total_cnt",
    "des",
    "user_id",
    "tweet_id",
]


def write_tsv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file, delimiter="\t"))


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is not None and str(value) != "":
            return str(value)
    return ""


def _merge_user_fields(row: dict[str, Any], user: dict[str, Any] | None) -> None:
    if not user:
        return
    row["uid"] = _first_non_empty(row.get("uid"), user.get("id"), user.get("idstr"))
    row["user_id"] = _first_non_empty(row.get("user_id"), user.get("id"), user.get("idstr"))
    row["favourites_count"] = _first_non_empty(user.get("favourites_count"), row.get("favourites_count"))
    row["statuses_count"] = _first_non_empty(user.get("statuses_count"), row.get("statuses_count"))
    row["friends_count"] = _first_non_empty(user.get("friends_count"), row.get("friends_count"))
    row["followers_count"] = _first_non_empty(user.get("followers_count"), row.get("followers_count"))
    row["bi_followers_count"] = _first_non_empty(user.get("bi_followers_count"), row.get("bi_followers_count"))
    row["credit_score"] = _first_non_empty(user.get("credit_score"), row.get("credit_score"))
    row["verified"] = _first_non_empty(user.get("verified"), row.get("verified"))
    row["des"] = _first_non_empty(user.get("description"), row.get("des"))


def _merge_profile_fields(row: dict[str, Any], profile: dict[str, Any] | None) -> None:
    if not profile:
        return
    for field in (
        "favourites_count",
        "statuses_count",
        "friends_count",
        "followers_count",
        "bi_followers_count",
        "credit_score",
        "verified",
        "des",
    ):
        row[field] = _first_non_empty(row.get(field), profile.get(field))


def _merge_status_fields(row: dict[str, Any], status: dict[str, Any] | None) -> dict[str, Any] | None:
    if not status:
        return None
    row["time"] = _first_non_empty(row.get("time"), status.get("created_at"))
    row["raw"] = _first_non_empty(row.get("raw"), status.get("text"))
    row["tweet_id"] = _first_non_empty(row.get("tweet_id"), status.get("id"), status.get("idstr"))
    row["comment_cnt"] = _first_non_empty(status.get("comments_count"), row.get("comment_cnt"))
    row["like_cnt"] = _first_non_empty(status.get("attitudes_count"), row.get("like_cnt"))
    row["repost_cnt"] = _first_non_empty(status.get("reposts_count"), row.get("repost_cnt"))
    user = status.get("user")
    return user if isinstance(user, dict) else None


def _status_key(row: dict[str, Any]) -> str:
    return str(row.get("tweet_id") or row.get("mid") or row.get("reported_weibo_url") or "").strip()


def _lookup_status(
    status_fields: dict[str, dict[str, Any]] | None,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    if not status_fields:
        return None
    keys = [
        str(row.get("tweet_id") or "").strip(),
        str(row.get("mid") or "").strip(),
        str(row.get("reported_weibo_url") or "").strip(),
        _status_key(row),
    ]
    for key in keys:
        if key and key in status_fields:
            return status_fields[key]
    return None


def build_dataset(
    notices: list[dict[str, Any]],
    api: Optional[WeiboAPI] = None,
    profile_fields: Optional[dict[str, dict[str, Any]]] = None,
    status_fields: Optional[dict[str, dict[str, Any]]] = None,
    fetch_comment_likes: bool = False,
    comment_pages: int = 0,
    require_original_link: bool = False,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for notice in notices:
        if require_original_link and not (notice.get("tweet_id") and notice.get("reported_weibo_url")):
            continue
        key = notice.get("tweet_id") or notice.get("reported_weibo_url") or notice.get("rid") or notice.get("notice_id")
        groups[str(key)].append(notice)

    dataset: list[dict[str, Any]] = []
    for _, items in groups.items():
        base = items[0]
        explicit_counts = [_to_int(item.get("report_cnt_explicit")) for item in items if item.get("report_cnt_explicit")]
        report_cnt = max(explicit_counts) if explicit_counts else len(items)

        row: dict[str, Any] = {
            "uid": base.get("uid", ""),
            "labels": base.get("labels", "不实信息"),
            "time": base.get("time", ""),
            "raw": base.get("raw", ""),
            "favourites_count": "",
            "statuses_count": "",
            "friends_count": "",
            "followers_count": "",
            "bi_followers_count": "",
            "credit_score": "",
            "verified": "",
            "comment_cnt": "",
            "comment_like_cnt": "",
            "like_cnt": "",
            "repost_cnt": "",
            "report_cnt": str(report_cnt),
            "total_cnt": "",
            "des": base.get("des", ""),
            "user_id": base.get("user_id") or base.get("uid", ""),
            "tweet_id": base.get("tweet_id", ""),
        }

        page_status_user = None
        page_status = _lookup_status(status_fields, base)
        if page_status:
            if page_status.get("status_available") == "false":
                continue
            page_status_user = _merge_status_fields(row, page_status)
        if page_status_user:
            _merge_user_fields(row, page_status_user)

        if api:
            status_user = None
            if row["tweet_id"]:
                status = api.status_show(row["tweet_id"])
                status_user = _merge_status_fields(row, status)
            if status_user:
                _merge_user_fields(row, status_user)
            elif row["uid"]:
                _merge_user_fields(row, api.user_show(uid=row["uid"]))

            if fetch_comment_likes and row["tweet_id"]:
                row["comment_like_cnt"] = api.comment_like_sum(row["tweet_id"], max_pages=comment_pages)

        if profile_fields:
            profile_key = str(row.get("uid") or row.get("user_id") or "")
            _merge_profile_fields(row, profile_fields.get(profile_key))

        total_fields = ("repost_cnt", "like_cnt", "comment_cnt", "comment_like_cnt")
        has_total_source = any(str(row.get(field) or "") != "" for field in total_fields)
        total_cnt = (
            _to_int(row.get("repost_cnt"))
            + _to_int(row.get("like_cnt"))
            + _to_int(row.get("comment_cnt"))
            + _to_int(row.get("comment_like_cnt"))
        )
        row["total_cnt"] = str(total_cnt) if has_total_source else ""
        dataset.append(row)

    return dataset
