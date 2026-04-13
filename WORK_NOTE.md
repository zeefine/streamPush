# Work Note (2026-04-13)

## 本轮完成
- 项目目录从 `deputyou` 重命名为 `streamPush`。
- 新闻推送链路完善：RSS 抓取、LLM 批量分类、按关键词分组摘要、飞书推送。
- 增加 LLM 调用重试机制（指数退避 + 抖动），并增强对 provider 包装错误（如 524）的重试识别。
- 增加运行日志：抓取统计、分类/摘要阶段、重试过程、飞书发送结果。
- 实现 URL 规范化去参数去重（追踪参数清理 + 规范化链接去重）。
- 配置治理优化：关键词、去参数规则、重试状态码、分类/摘要模板支持配置化。
- 配置文件整理：
  - `settings.toml` 保存默认规则与模板。
  - `.env.example` 保留环境与密钥相关项（含可选关键词覆盖）。

## 当前运行命令
```bash
uv run streampush-news
```

## 下一步建议
- 增加“跨运行去重”（SQLite 持久化已推送记录），避免同一新闻在不同批次重复推送。

## 本次补充更新（同日）
- 新增 LLM token 消耗记录：在统一调用层输出 `llm_token_usage` 日志，覆盖 `filter` 与 `summary` 两类调用。
- 新增 token 字段兼容解析：优先 `usage_metadata`，兜底 `response_metadata.token_usage`。
- 修复摘要阶段上游 `524` 导致任务中断的问题：增加本地摘要降级逻辑，超时后返回可读简报并继续流程。
- 新增测试：`tests/test_news_agent_fallback.py`，校验 524 兜底摘要结构与链接内容。

## 本次验证
```bash
uv run python -m unittest discover -s tests -p 'test_*.py'
python3 -m compileall app tests
```
