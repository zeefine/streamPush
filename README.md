# streamPush News Agent

新闻推送 Agent：抓取 RSS 新闻，使用 LLM 提炼重点，并通过飞书发送给你。

## 现在的架构

- `app/news_fetcher.py`：抓取和筛选新闻（RSS/Atom）
- `app/news_agent.py`：LLM 先判定新闻是否匹配关键词，再按关键词分组生成中文日报摘要
- `app/feishu.py`：调用飞书消息 API 推送
- `app/runner.py`：单次执行入口，适合定时任务

## 配置说明

### 文件配置（默认策略）

文件：`app/settings.toml`

- `[llm]`：`model_name`、`base_url`、`temperature`、`timeout_seconds`、`retry_max_attempts`、`retry_base_delay_seconds`、`retry_max_delay_seconds`
- `[feishu]`：`base_url`、`recipient_id_type`（`chat_id` 或 `open_id`）
- `[logging]`：`level`、`format`
- `[news]`：`rss_urls`、`lookback_hours`、`max_items`
- `[prompt]`：`target_keywords`、`filter_instruction`、`filter_system_prompt`、`filter_output_schema`、`filter_batch_size`、`summary_grouping_rules`、`summary_output_template`、新闻提炼提示词

建议放在 `settings.toml` 的核心项：
- `rss_urls`
- `filter_batch_size`
- `filter_system_prompt`
- `summary_output_template`
- `retry_*` 默认值

### 环境变量（密钥和环境差异）

文件：`.env`

- `LLM_API_KEY`（必填）
- `FEISHU_APP_ID`（必填）
- `FEISHU_APP_SECRET`（必填）
- `FEISHU_CHAT_ID` 或 `FEISHU_OPEN_ID`（至少一个）
- `NEWS_TARGET_KEYWORDS`（可选，逗号分隔，覆盖 `settings.toml` 的 `prompt.target_keywords`）

## 运行

```bash
uv sync
uv run streampush-news
```

运行一次会完成：抓新闻 -> 生成摘要 -> 推送飞书。
其中“是否属于目标关键词新闻”由 LLM 基于 `title+summary` 批量判断，不再使用字符串包含过滤。
运行日志会输出：抓取统计、LLM 分类/摘要进度、重试信息、飞书发送结果。

## 定时推送（cron 示例）

每天上午 9:00 推送一次：

```bash
0 9 * * * cd /Users/fine/PyProjects/streamPush && /usr/local/bin/uv run streampush-news >> /tmp/streampush-news.log 2>&1
```

## 飞书侧最小要求

1. 在飞书开放平台创建企业自建应用。
2. 申请并开通发送消息权限。
3. 用 `FEISHU_APP_ID/FEISHU_APP_SECRET` 获取 tenant access token。
4. 配置接收目标（群 `chat_id` 或个人 `open_id`）。

这个方案只做主动推送，不依赖事件回调，不需要内网穿透。
