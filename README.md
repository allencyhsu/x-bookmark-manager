# XBM — X Bookmarks Manager

用 Playwright 瀏覽器自動化抓取 X 書籤，LLM 分類，存入 SQLite。**不需要付費 API**。

## 前置需求

| 項目 | 說明 |
|------|------|
| **Python** | ≥ 3.11 |
| **UV** | [安裝 UV](https://docs.astral.sh/uv/) |
| **LLM** | 本地 Qwen3.5 server 或任何 OpenAI 相容 API |

## 安裝

```bash
cd XBM
uv sync
# 安裝 Chromium 瀏覽器
uv run playwright install chromium
```

## 設定

```bash
cp .env.example .env
# 如需修改 LLM 或 DB 路徑，編輯 .env
```

## 使用方式

```bash
# 1) 首次使用 — 登入 X（開啟瀏覽器手動登入，完成後關閉瀏覽器）
uv run python main.py login

# 2) 抓取書籤（背景執行，攔截內部 API）
uv run python main.py fetch

# 抓取時顯示瀏覽器
uv run python main.py fetch --visible

# 限制抓取數量
uv run python main.py fetch -n 50

# 3) 分類書籤
uv run python main.py classify

# 4) 一鍵完成：抓取 + 分類
uv run python main.py run

# 5) 查看統計
uv run python main.py stats

# 6) 匯出 CSV
uv run python main.py export -o my_bookmarks.csv
```

## 運作原理

1. **登入**: Playwright 開啟 Chromium，你手動登入 X，session 保存到 `browser_data/`
2. **抓取**: 造訪書籤頁 → 攔截 X 內部 GraphQL API 回應 → 取得結構化推文資料 → 自動捲動載入更多
3. **分類**: 透過本地 LLM (Qwen3.5) 將推文分成 Tech / Design / Business / Life / News / Other
4. **儲存**: 所有資料存入 SQLite (`bookmarks.db`)

## 架構

```
main.py          CLI 入口
├─ scraper.py    Playwright 書籤抓取（GraphQL 攔截）
├─ classifier.py LLM 分類（OpenAI 相容 API）
├─ database.py   SQLite 儲存
└─ config.py     設定載入（.env）
```

## 分類類別

| 類別 | 說明 |
|------|------|
| Tech | 技術、程式、AI |
| Design | 設計、UI/UX |
| Business | 商業、創業、行銷 |
| Life | 生活、思考、個人成長 |
| News | 新聞、時事 |
| Other | 其他 |

## 資料庫查詢

```bash
# 查看 Tech 類別
sqlite3 bookmarks.db "SELECT author_username, substr(text,1,80) FROM bookmarks WHERE category='Tech' LIMIT 10;"

# 各分類統計
sqlite3 bookmarks.db "SELECT category, COUNT(*) FROM bookmarks GROUP BY category;"
```
