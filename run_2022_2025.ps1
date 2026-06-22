$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$OutputDir = Join-Path $ProjectRoot "weibo_rumor_2022_2025"

& $Python (Join-Path $ProjectRoot "run_crawl.py") `
  --start-page 1 `
  --end-page 10000 `
  --status 4 `
  --date-from 2022-01-01 `
  --date-to 2025-12-31 `
  --output-dir $OutputDir `
  --resume `
  --keep-html `
  --no-api `
  --enrich-status-pages `
  --enrich-profile-pages `
  --require-original-link `
  --browser-channel msedge `
  --headless `
  --notice-page-sleep-ms 2500 `
  --notice-detail-sleep-ms 1200 `
  --status-sleep-ms 3500 `
  --profile-sleep-ms 2500 `
  --notice-blocked-sleep-seconds 180 `
  --status-blocked-sleep-seconds 180 `
  --profile-blocked-sleep-seconds 180 `
  --status-max-consecutive-blocked 5
