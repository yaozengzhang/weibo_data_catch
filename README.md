# Weibo False-Rumor Notice Crawler

这个项目抓取微博社区管理中心“不实信息”模块的结果公示页。流程是先从列表页提取 `/show?rid=...` 详情入口，再打开详情页解析被举报微博原文、原微博链接和被举报人信息，并尽量用微博开放平台 API 补充用户和微博互动字段。

## 安装

```powershell
cd E:\task3_weibodata_zyz
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

如需 API 补字段，复制 `.env.example` 为 `.env`，填入：

```text
WEIBO_ACCESS_TOKEN=你的微博开放平台access_token
```

没有 token 也可以抓公示页，API 字段会留空。

## 第一次运行和登录

```powershell
python run_crawl.py --start-page 1 --end-page 5 --status 4 --login --keep-html
```

运行后会弹出浏览器：

1. 在浏览器里完成微博登录。
2. 登录后回到终端按 Enter。
3. 脚本继续抓取 `type=5` 的不实信息页面。

默认使用 Microsoft Edge，登录状态保存在 `data/browser_profile`，后续可以不加 `--login` 复用。

## 常用命令

只抓页面，不调用 API：

```powershell
python run_crawl.py --start-page 1 --end-page 20 --status 4 --no-api
```

只抓 1 页，并额外打开被举报人的用户主页补充粉丝数、关注数、简介等公开字段：

```powershell
python run_crawl.py --start-page 1 --end-page 1 --status 4 --login --keep-html --no-api --enrich-profile-pages
```

只保留详情页里存在“原文”按钮的记录；没有原文按钮的详情记录会直接丢弃，不写入原始 TSV：

```powershell
python run_crawl.py --start-page 1 --end-page 1 --status 4 --require-original-link
```

抓页面并用 API 补字段：

```powershell
python run_crawl.py --start-page 1 --end-page 20 --status 4
```

如果你确认目标页面筛选状态是 `status=0`：

```powershell
python run_crawl.py --start-page 1 --end-page 20 --status 0 --login
```

抓取 `2022-01-01` 到 `2025-12-31` 期间“不实信息-结果公示”样本，并输出到独立目录：

```powershell
.\run_2022_2025.ps1
```

等价的完整命令是：

```powershell
python run_crawl.py `
  --start-page 1 `
  --end-page 10000 `
  --status 4 `
  --date-from 2022-01-01 `
  --date-to 2025-12-31 `
  --output-dir E:\task3_weibodata_zyz\weibo_rumor_2022_2025 `
  --resume `
  --keep-html `
  --no-api `
  --enrich-status-pages `
  --enrich-profile-pages `
  --require-original-link `
  --browser-channel msedge `
  --headless
```

日期范围按结果公示列表中的 `report_time` 过滤；原微博发布时间 `time` 可能早于公示日期，这是正常情况。

若遇到微博 `403/418/429` 等限流，脚本会等待后重试。任务中断后重新运行同一命令即可从 `crawl_state.json` 和已有 TSV 继续。

如果普通浏览器手动能打开详情页，但自动脚本触发访问限制，可以使用可见 Edge 慢速模式：

```powershell
.\run_2022_2025_human.ps1
```

该模式会强制显示 Edge 窗口，并放慢列表页、详情页、原微博页和用户页访问间隔。遇到社区管理中心“你的访问超过今日上限”时会立即停止，并把 `crawl_state.json` 的 `next_page` 保持在当前页，避免把限流页误判成“无原文按钮”。

## 输出

原始公示记录：

```text
data/notices_raw.tsv
```

最终数据集：

```text
data/weibo_false_rumor_dataset.tsv
```

使用 `--output-dir E:\task3_weibodata_zyz\weibo_rumor_2022_2025` 时，输出文件包括：

```text
notices_raw.tsv                 原始结果公示详情记录
weibo_false_rumor_dataset.tsv   最终建模主表
status_fetch.tsv                原微博互动数抓取结果
failed_statuses.tsv             原微博互动数失败/限流/不可见记录
profiles.tsv                    用户主页公开字段
failed_profiles.tsv             用户主页失败记录
crawl_pages.tsv                 每页抓取统计
crawl_state.json                断点续爬状态
html_debug/                     可选 HTML 快照
```

最终字段包含：

```text
uid labels time raw favourites_count statuses_count friends_count followers_count bi_followers_count credit_score verified comment_cnt comment_like_cnt like_cnt repost_cnt report_cnt total_cnt des user_id tweet_id
```

`report_cnt` 的来源优先级：

1. 页面显式出现的“举报 N 次”。
2. 页面没有显式次数时，按同一 `tweet_id` 在公示记录中出现的次数统计。

`total_cnt = repost_cnt + like_cnt + comment_cnt + comment_like_cnt`，不包含 `report_cnt`。

## 注意

`credit_score` 和 `comment_like_cnt` 不是当前官方 API 中稳定保证的字段，抓不到时会留空。

用户主页补字段依赖登录后页面实际展示内容。若页面要求验证码或安全验证，需要在弹出的浏览器中手动完成；脚本只解析正常页面上公开显示的数据。
