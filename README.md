# 2026 美股财报雷达｜26只核心观察股｜Apple Calendar 自动订阅版 📅

这是一个可以放在 GitHub 上自动维护的 Apple Calendar 订阅日历。

工作方式：

1. GitHub Actions 每天按美西时间 **06:37** 与 **18:37** 自动运行。
2. 程序从 **Finnhub Earnings Calendar API** 抓取 26 只观察股的 2026 财报日期。
3. 若日期发生新增或变化，仓库中的 `earnings_calendar.ics` 会自动更新。
4. iPhone 只订阅一次固定 URL，后面不需要重新上传或覆盖文件。

> 自动抓取到的未来日期会标为 `⏳ 数据源预告`。财报日期临近且涉及真实交易时，请以公司 Investor Relations 官网最新公告为准。

---

## 观察股票名单

| 主题 | Tickers |
|---|---|
| AI 大厂 / CapEx | MSFT, GOOGL, META, AMZN, ORCL |
| 芯片 / 存储 | NVDA, AMD, AVGO, MU, SNDK |
| 数据中心基础设施 | CRWV, ANET, VRT, GLW |
| AI 软件 | SNOW, PLTR |
| 太空 / 航天 | RKLB, LUNR, ASTS |
| 军工 / 防务 | RTX, LMT |
| 电力 / 核能 | CEG, VST, OKLO, LEU |
| 额外关注 | TSLA |

---

## 你只需要设置一次

### 第一步：注册 Finnhub API key

进入 Finnhub 注册并获取个人 API key：

- https://finnhub.io/register
- https://finnhub.io/docs/api

不要把 API key 写进公开文件或提交到 GitHub；下一步会把它安全地存到 GitHub Secret 中。

### 第二步：新建一个公开 GitHub 仓库

推荐仓库名：

```text
chloe-earnings-calendar
```

选择 **Public**，因为 Apple Calendar 需要直接访问公开的 `.ics` 链接；这个仓库只放公开财报数据，不会放你的持仓或账户信息。

把本文件包中的所有内容上传到仓库根目录，上传完成后应当能看到：

```text
.github/workflows/update_calendar.yml
data/tickers.json
data/manual_confirmed_events.json
data/api_cache.json
scripts/generate_calendar.py
earnings_calendar.ics
.nojekyll
README.md
```

尤其确认隐藏目录 `.github/workflows/` 没有漏掉，否则不会自动运行。

### 第三步：把 API key 放入 GitHub Secret

进入你的仓库：

```text
Settings → Secrets and variables → Actions → New repository secret
```

填写：

```text
Name: FINNHUB_API_KEY
Secret: 你的 Finnhub API key
```

保存。

### 第四步：第一次手动运行自动更新

进入仓库：

```text
Actions → Update earnings calendar → Run workflow
```

运行成功后，程序会自动把新的 `earnings_calendar.ics` 提交回仓库。之后不用再手动运行：工作流会每天美西时间 06:37 与 18:37 检查两次。

> 若 Finnhub 临时失败，程序不会把已有日历清空；某只股票请求失败时，会尽量保留缓存里的未过期财报节点。

### 第五步：启用 GitHub Pages，获得漂亮且稳定的订阅 URL

进入仓库：

```text
Settings → Pages → Build and deployment → Source: Deploy from a branch
Branch: main / (root) → Save
```

Pages 发布后，你的订阅链接会是：

```text
https://你的GitHub用户名.github.io/chloe-earnings-calendar/earnings_calendar.ics
```

仓库名不同，就把链接中的 `chloe-earnings-calendar` 换成实际仓库名。

### 第六步：在 iPhone 日历里订阅

在 iPhone 打开：

```text
日历 App → Calendars/日历 → Add Calendar/添加日历 → Add Subscription Calendar/添加订阅日历
```

粘贴 GitHub Pages 的 `.ics` URL，Account 选择 **iCloud**，保存即可。

订阅后，日历会显示类似：

```text
🔥 ⏳ 财报｜NVDA NVIDIA｜AI GPU / Data Center
🔥 ⏳ 财报｜SNOW Snowflake｜AI Data Cloud
🟠 ⏳ 财报｜OKLO Oklo｜Advanced Nuclear / Regulatory
```

`🔥/🟠` 是你的关注优先级；`⏳` 表示来自自动数据源、仍需在交易临近时核对公司 IR。

---

## 以后怎么维护

正常情况下你不需要维护文件。

### 增减股票

只需要修改：

```text
data/tickers.json
```

新增一行公司配置，或删除某一项；下次 Action 运行时日历会自动变化。

### 可选：把某个日期标成官网确认 `✅`

这不是必须步骤；只有你特别想把某个关键财报锁定为官网确认时才需要。

在 `data/manual_confirmed_events.json` 中加入，例如：

```json
[
  {
    "symbol": "AVGO",
    "company": "Broadcom",
    "priority": "🔥",
    "theme": "ASIC / AI Networking",
    "date": "2026-06-03",
    "timing": "盘后发布；5:00 PM ET 电话会",
    "url": "https://investors.broadcom.com/",
    "source_type": "manual_confirmed"
  }
]
```

提示：人工锁定的未来日期如果公司后来改期，也需要你手动删除或更新该条；因此日常使用建议保留自动版即可。

---

## 重要提醒

- Finnhub API 返回的是财报日历数据，不等同于公司 IR 官网最终公告；日期可能变化。
- 这个日历适合做“提前看到催化剂”的交易雷达，不应作为下单前的唯一确认来源。
- GitHub 的公开仓库 scheduled workflow 在长期无仓库活动时可能被自动停用；财报季偶尔查看一下 `Actions` 是否正常运行即可。
- Apple Calendar 对订阅更新的显示节奏由 Apple 端刷新决定；需要立即确认时，也可以在日历中手动刷新。

---

## 数据及平台文档

- Finnhub API 文档：https://finnhub.io/docs/api
- Finnhub 官方 Python 客户端中 Earnings Calendar 接口：`/calendar/earnings`
- GitHub Actions scheduled workflows：https://docs.github.com/actions/using-workflows/events-that-trigger-workflows
- Apple Calendar subscription：https://support.apple.com/en-us/102301
