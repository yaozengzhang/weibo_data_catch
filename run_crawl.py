from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl Weibo community false-information notices and build a TSV dataset."
    )
    parser.add_argument("--start-page", type=int, default=1, help="First notice page to crawl.")
    parser.add_argument("--end-page", type=int, default=1, help="Last notice page to crawl.")
    parser.add_argument("--status", type=int, default=4, help="Notice status filter. Paper uses status=4.")
    parser.add_argument("--type", dest="notice_type", type=int, default=5, help="Notice type. False information is type=5.")
    parser.add_argument("--login", action="store_true", help="Pause after opening browser so you can log in manually.")
    parser.add_argument("--headless", action="store_true", help="Run browser without UI. Use only after login cookies are saved.")
    parser.add_argument("--browser-channel", default="msedge", help="Playwright browser channel. Use msedge for Microsoft Edge.")
    parser.add_argument("--keep-html", action="store_true", help="Save crawled HTML pages under data/html_debug.")
    parser.add_argument("--browser-profile", default="data/browser_profile", help="Playwright persistent browser profile path.")
    parser.add_argument("--raw-output", default="data/notices_raw.tsv", help="Output TSV for raw public notice records.")
    parser.add_argument("--output", default="data/weibo_false_rumor_dataset.tsv", help="Final dataset TSV path.")
    parser.add_argument("--output-dir", default="", help="Directory for all crawl outputs. Overrides --raw-output and --output when set.")
    parser.add_argument("--date-from", default="", help="Inclusive report date lower bound, e.g. 2022-01-01.")
    parser.add_argument("--date-to", default="", help="Inclusive report date upper bound, e.g. 2025-12-31.")
    parser.add_argument("--resume", action="store_true", help="Resume from crawl_state.json and existing TSV outputs.")
    parser.add_argument("--stop-before-date", action="store_true", default=True, help="Stop paging once list rows are older than --date-from.")
    parser.add_argument("--state-file", default="crawl_state.json", help="State JSON filename under --output-dir.")
    parser.add_argument("--access-token", default="", help="Weibo API access token. Defaults to WEIBO_ACCESS_TOKEN in .env.")
    parser.add_argument("--no-api", action="store_true", help="Skip Weibo Open API enrichment.")
    parser.add_argument("--api-sleep", type=float, default=1.0, help="Seconds to sleep between API calls.")
    parser.add_argument("--fetch-comment-likes", action="store_true", help="Try to sum likes received by replies.")
    parser.add_argument("--comment-pages", type=int, default=1, help="Comment pages to scan when --fetch-comment-likes is set.")
    parser.add_argument("--require-original-link", action="store_true", help="Only keep records with an original Weibo link and tweet_id.")
    parser.add_argument("--enrich-profile-pages", action="store_true", help="Open reported users' profile pages and parse public profile fields.")
    parser.add_argument("--profile-page-limit", type=int, default=0, help="Max users to enrich from profile pages. 0 means all users found.")
    parser.add_argument("--profile-sleep-ms", type=int, default=1200, help="Delay between profile page visits.")
    parser.add_argument("--profile-retry-count", type=int, default=2, help="Retries for each profile page.")
    parser.add_argument("--profile-blocked-sleep-seconds", type=int, default=90, help="Sleep seconds after profile-page anti-crawl errors.")
    parser.add_argument("--enrich-status-pages", action="store_true", help="Open original Weibo pages and parse repost/comment/like counts.")
    parser.add_argument("--status-page-limit", type=int, default=0, help="Max original Weibo pages to enrich. 0 means all statuses found.")
    parser.add_argument("--status-sleep-ms", type=int, default=2500, help="Delay between original Weibo page visits.")
    parser.add_argument("--status-retry-count", type=int, default=2, help="Retries for original Weibo status API/page fetches.")
    parser.add_argument("--status-blocked-sleep-seconds", type=int, default=120, help="Sleep seconds after status anti-crawl errors.")
    parser.add_argument("--status-max-consecutive-blocked", type=int, default=5, help="Stop status enrichment after this many consecutive blocked requests.")
    parser.add_argument("--notice-page-sleep-ms", type=int, default=1800, help="Delay between notice list pages.")
    parser.add_argument("--notice-detail-sleep-ms", type=int, default=900, help="Delay between notice detail pages.")
    parser.add_argument("--notice-retry-count", type=int, default=3, help="Retries for notice list/detail pages.")
    parser.add_argument("--notice-blocked-sleep-seconds", type=int, default=120, help="Sleep seconds after notice anti-crawl errors.")
    return parser.parse_args()


def _resolve_output_paths(args: argparse.Namespace) -> dict[str, Path]:
    if args.output_dir:
        output_dir = Path(args.output_dir)
        if not output_dir.is_absolute():
            output_dir = PROJECT_ROOT / output_dir
        return {
            "output_dir": output_dir,
            "raw": output_dir / "notices_raw.tsv",
            "dataset": output_dir / "weibo_false_rumor_dataset.tsv",
            "statuses": output_dir / "status_fetch.tsv",
            "failed_statuses": output_dir / "failed_statuses.tsv",
            "profiles": output_dir / "profiles.tsv",
            "failed_profiles": output_dir / "failed_profiles.tsv",
            "page_log": output_dir / "crawl_pages.tsv",
            "state": output_dir / args.state_file,
            "html_dir": output_dir / "html_debug",
        }
    return {
        "output_dir": PROJECT_ROOT,
        "raw": PROJECT_ROOT / args.raw_output,
        "dataset": PROJECT_ROOT / args.output,
        "statuses": PROJECT_ROOT / "data" / "status_fetch.tsv",
        "failed_statuses": PROJECT_ROOT / "data" / "failed_statuses.tsv",
        "profiles": PROJECT_ROOT / "data" / "profiles.tsv",
        "failed_profiles": PROJECT_ROOT / "data" / "failed_profiles.tsv",
        "page_log": PROJECT_ROOT / "data" / "crawl_pages.tsv",
        "state": PROJECT_ROOT / "data" / args.state_file,
        "html_dir": PROJECT_ROOT / "data" / "html_debug",
    }


def _row_lookup(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    from crawler.run_state import row_key

    return {row_key(row): row for row in rows if row_key(row)}


def _notice_status_lookup(status_fields: dict[str, dict[str, object]], notice: dict[str, object]) -> dict[str, object] | None:
    for key in (
        str(notice.get("tweet_id") or "").strip(),
        str(notice.get("mid") or "").strip(),
        str(notice.get("reported_weibo_url") or "").strip(),
    ):
        if key and key in status_fields:
            return status_fields[key]
    return None


def _filter_available_notices(
    notices: list[dict[str, object]],
    status_fields: dict[str, dict[str, object]] | None,
) -> list[dict[str, object]]:
    if not status_fields:
        return notices
    return [
        notice
        for notice in notices
        if (_notice_status_lookup(status_fields, notice) or {}).get("status_available") != "false"
    ]


def main() -> None:
    args = parse_args()

    try:
        from dotenv import load_dotenv

        from crawler.build_dataset import DATASET_COLUMNS, NOTICE_COLUMNS, build_dataset, write_tsv
        from crawler.notice_crawler import NoticeCrawler, NoticeRateLimitError, parse_date_arg
        from crawler.profile_crawler import PROFILE_COLUMNS, PROFILE_FAILURE_COLUMNS, ProfileCrawler
        from crawler.run_state import load_rows, merge_rows, read_json, row_key, write_json, write_rows
        from crawler.status_crawler import STATUS_COLUMNS, StatusCrawler
        from crawler.weibo_api import WeiboAPI
    except ImportError as exc:
        raise SystemExit(f"缺少依赖: {exc}. 请先运行 pip install -r requirements.txt") from exc

    load_dotenv(PROJECT_ROOT / ".env")

    if args.end_page < args.start_page:
        raise SystemExit("--end-page must be greater than or equal to --start-page")

    date_from = parse_date_arg(args.date_from)
    date_to = parse_date_arg(args.date_to)
    if date_from and date_to and date_to < date_from:
        raise SystemExit("--date-to must be greater than or equal to --date-from")

    paths = _resolve_output_paths(args)
    paths["output_dir"].mkdir(parents=True, exist_ok=True)

    crawl_state = read_json(paths["state"]) if args.resume else {}
    start_page = args.start_page
    if args.resume and crawl_state.get("next_page"):
        start_page = max(start_page, int(crawl_state["next_page"]))
        print(f"断点续爬，从第 {start_page} 页继续。")

    profile_path = PROJECT_ROOT / args.browser_profile
    html_dir = paths["html_dir"]
    crawler = NoticeCrawler(
        user_data_dir=profile_path,
        headless=args.headless,
        keep_html=args.keep_html,
        html_dir=html_dir,
        browser_channel=args.browser_channel,
        page_sleep_ms=args.notice_page_sleep_ms,
        detail_sleep_ms=args.notice_detail_sleep_ms,
        retry_count=args.notice_retry_count,
        blocked_sleep_seconds=args.notice_blocked_sleep_seconds,
    )

    existing_notices = load_rows(paths["raw"]) if args.resume else []
    page_logs = load_rows(paths["page_log"]) if args.resume else []

    def on_page_records(page_number: int, page_records: list[dict[str, Any]], page_stats: dict[str, Any]) -> None:
        nonlocal existing_notices, page_logs
        existing_notices = merge_rows(existing_notices, page_records)
        page_log = {
            "page": str(page_number),
            **{key: str(value) for key, value in page_stats.items()},
        }
        page_logs = merge_rows(page_logs, [page_log])
        write_rows(paths["raw"], existing_notices, NOTICE_COLUMNS)
        write_rows(
            paths["page_log"],
            page_logs,
            [
                "page",
                "source_page",
                "list_count",
                "detail_count",
                "kept_count",
                "skipped_newer",
                "skipped_older",
                "skipped_no_original",
                "skipped_unknown_date",
                "blocked",
                "blocked_reason",
                "stop_after_page",
            ],
        )
        blocked = str(page_stats.get("blocked", "")).lower() == "true"
        write_json(
            paths["state"],
            {
                "stage": "notices",
                "date_from": args.date_from,
                "date_to": args.date_to,
                "last_page": page_number,
                "next_page": page_number if blocked else page_number + 1,
                "notice_rows": len(existing_notices),
                "blocked": blocked,
                "blocked_reason": page_stats.get("blocked_reason", ""),
            },
        )

    try:
        notices = crawler.crawl(
            start_page=start_page,
            end_page=args.end_page,
            status=args.status,
            notice_type=args.notice_type,
            login=args.login,
            require_original_link=args.require_original_link,
            date_from=date_from,
            date_to=date_to,
            stop_before_date=args.stop_before_date,
            on_page_records=on_page_records,
        )
    except NoticeRateLimitError as exc:
        notices = []
        write_json(
            paths["state"],
            {
                "stage": "blocked",
                "date_from": args.date_from,
                "date_to": args.date_to,
                "last_page": exc.page_number,
                "next_page": exc.page_number,
                "notice_rows": len(existing_notices),
                "blocked": True,
                "blocked_reason": str(exc),
                "blocked_detail_url": exc.detail_url,
            },
        )
        write_rows(paths["raw"], existing_notices, NOTICE_COLUMNS)
        print(f"检测到社区管理中心访问上限，已停止；下次从第 {exc.page_number} 页继续。")
        return
    notices = merge_rows(existing_notices, notices)

    status_fields = None
    if args.enrich_status_pages:
        existing_status_rows = load_rows(paths["statuses"]) if args.resume else []
        existing_status = _row_lookup(existing_status_rows)
        status_targets = []
        for notice in notices:
            key = row_key(notice)
            existing = existing_status.get(key)
            if existing and existing.get("status_available") in {"true", "false"}:
                continue
            status_targets.append(notice)
        status_crawler = StatusCrawler(
            user_data_dir=profile_path,
            headless=args.headless,
            keep_html=args.keep_html,
            html_dir=html_dir / "statuses",
            sleep_ms=args.status_sleep_ms,
            browser_channel=args.browser_channel,
            retry_count=args.status_retry_count,
            blocked_sleep_seconds=args.status_blocked_sleep_seconds,
            max_consecutive_blocked=args.status_max_consecutive_blocked,
        )
        new_status_fields = status_crawler.enrich_notices(status_targets, limit=args.status_page_limit)
        status_rows = merge_rows(existing_status_rows, list(new_status_fields.values()))
        write_tsv(paths["statuses"], status_rows, STATUS_COLUMNS)
        failed_status_rows = [
            row
            for row in status_rows
            if row.get("status_available") != "true" or row.get("fetch_status") != "ok"
        ]
        write_tsv(paths["failed_statuses"], failed_status_rows, STATUS_COLUMNS)
        status_fields = _row_lookup(status_rows)
        before_count = len(notices)
        notices = _filter_available_notices(notices, status_fields)
        dropped_count = before_count - len(notices)
        if dropped_count:
            print(f"已丢弃原微博不可访问记录: {dropped_count}")
        write_rows(paths["raw"], notices, NOTICE_COLUMNS)
        write_json(
            paths["state"],
            {
                "stage": "statuses",
                "date_from": args.date_from,
                "date_to": args.date_to,
                "notice_rows": len(notices),
                "status_rows": len(status_rows),
                "failed_status_rows": len(failed_status_rows),
            },
        )

    raw_output = paths["raw"]
    write_tsv(raw_output, notices, NOTICE_COLUMNS)
    print(f"已写入原始公示记录: {raw_output}")

    token = args.access_token or os.getenv("WEIBO_ACCESS_TOKEN", "")
    api = None
    if not args.no_api and token:
        api = WeiboAPI(access_token=token, sleep_seconds=args.api_sleep)
    elif not args.no_api:
        print("未提供 WEIBO_ACCESS_TOKEN，跳过微博开放平台 API 补字段。")

    profile_fields = None
    if args.enrich_profile_pages:
        existing_profile_rows = load_rows(paths["profiles"]) if args.resume else []
        existing_profiles = _row_lookup(existing_profile_rows)
        profile_targets = [
            notice
            for notice in notices
            if str(notice.get("uid") or notice.get("user_id") or "").strip() not in existing_profiles
        ]
        profile_crawler = ProfileCrawler(
            user_data_dir=profile_path,
            headless=args.headless,
            keep_html=args.keep_html,
            html_dir=html_dir / "profiles",
            sleep_ms=args.profile_sleep_ms,
            browser_channel=args.browser_channel,
            retry_count=args.profile_retry_count,
            blocked_sleep_seconds=args.profile_blocked_sleep_seconds,
        )
        new_profile_fields = profile_crawler.enrich_notices(profile_targets, limit=args.profile_page_limit)
        profile_rows = merge_rows(existing_profile_rows, list(new_profile_fields.values()))
        write_tsv(paths["profiles"], profile_rows, PROFILE_COLUMNS)
        failed_profiles = (load_rows(paths["failed_profiles"]) if args.resume else []) + profile_crawler.failures
        write_tsv(paths["failed_profiles"], failed_profiles, PROFILE_FAILURE_COLUMNS)
        profile_fields = _row_lookup(profile_rows)
        write_json(
            paths["state"],
            {
                "stage": "profiles",
                "date_from": args.date_from,
                "date_to": args.date_to,
                "notice_rows": len(notices),
                "profile_rows": len(profile_rows),
                "failed_profile_rows": len(failed_profiles),
            },
        )

    dataset = build_dataset(
        notices,
        api=api,
        profile_fields=profile_fields,
        status_fields=status_fields,
        fetch_comment_likes=args.fetch_comment_likes,
        comment_pages=args.comment_pages,
        require_original_link=args.require_original_link,
    )
    output = paths["dataset"]
    write_tsv(output, dataset, DATASET_COLUMNS)
    print(f"已写入最终数据集: {output}")
    write_json(
        paths["state"],
        {
            "stage": "done",
            "date_from": args.date_from,
            "date_to": args.date_to,
            "notice_rows": len(notices),
            "dataset_rows": len(dataset),
        },
    )


if __name__ == "__main__":
    main()
