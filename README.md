# OCS LLM Answerer

一个给 OCS（Online Course Script）用的**本地 LLM 答题服务**。它不改 OCS 源码，只实现 OCS 的 AnswererWrapper 协议：OCS 把题目/选项/题型/图片 POST 过来，服务返回 [题目, 答案, extra_data]，剩下的答案匹配、点选项、填空、结果面板、AI 标签全部由 OCS 自己完成。

- 本地服务：默认 127.0.0.1:8787
- 配置：内置 WebUI，打开 /setup 即可测试连接、生成 OCS 配置并保存 .env
- 模型：DeepSeek OpenAI 兼容 /chat/completions
- 项目管理：pyproject.toml + uv + uv.lock + CLI 入口
- 零源码：只加一份 OCS 题库配置
- 自用：SQLite 缓存/日志、可选 token、离线 mock 模式
- 当前适配：DeepSeek V4.1 Flash / V4 Pro（2026-10 API 文档）

开发设计、边界和验收标准见 [DEVELOPMENT.md](DEVELOPMENT.md)。DeepSeek 最新文档见 [api-docs.deepseek.com](https://api-docs.deepseek.com/zh-cn/)。

## 1. 快速开始

### 环境

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- DeepSeek API Key（没有 key 可以先用 mock 模式）

### 安装

```bash
cd ocs-llm-answerer
uv sync
cp .env.example .env
# 编辑 .env，至少填写 DEEPSEEK_API_KEY
```

uv sync 会同时安装项目本身和 dev 依赖（pytest），并生成/更新 .venv。生产环境可以只用：

```bash
uv sync --no-dev
```

### 启动

```bash
uv run ocs-llm-answerer
```

默认监听 127.0.0.1:8787。开发时自动重载：

```bash
uv run ocs-llm-answerer --reload
```

也可以直接用 uvicorn：

```bash
uv run uvicorn app.main:app --host 127.0.0.1 --port 8787
```

没有 DeepSeek key 时，先用 mock 验证 OCS 链路：

```bash
LLM_PROVIDER=mock uv run ocs-llm-answerer
```

mock 会按题型返回固定答案：单选 A、多选 AB、判断 对、填空 示例答案。它只用于验证格式和接入，不代表真实模型效果。

### WebUI 配置（推荐）

启动后打开：

~~~text
http://127.0.0.1:8787/setup
~~~

在页面里可以：

- 填写 DeepSeek API Key、模型、Base URL；
- 测试连接（会发送一次最小请求）；
- 配置思考模式、超时、max_tokens、置信度；
- 设置 HOST/PORT、API Token、SQLite、CORS；
- 一键生成/复制/下载 OCS 题库配置；
- 保存到 `.env`。

保存后需要重启服务生效。保存 API Key 后如果看到“已写入 .env，重启后生效”，说明文件已经写入，只是当前进程还没加载；重启服务即可。配置页默认只允许本机访问；设置 API_TOKEN 后需要先输入口令。页面不会把已保存的 API Key 回传到浏览器。

### 验证

```bash
curl -s http://127.0.0.1:8787/health
curl -s http://127.0.0.1:8787/api/answer \
  -H 'Content-Type: application/json' \
  -d '{"question":"1+1=?","options":["A. 1","B. 2"],"type":"single"}'
```

接口文档：http://127.0.0.1:8787/docs

## 2. DeepSeek 配置

### 模型

| 模型 | 说明 |
|---|---|
| deepseek-flash | 默认。DeepSeek-V4.1-Flash，支持文本 + 图片，速度快、成本低 |
| deepseek-v4-pro | 纯文本，更强；不支持图片输入 |
| deepseek-chat / deepseek-reasoner | 官方当前文档已不再列出；请迁移到上面的模型名 |

设置默认模型：

```dotenv
DEEPSEEK_MODEL=deepseek-flash
```

按题型覆盖：

```dotenv
MODEL_SINGLE=deepseek-flash
MODEL_MULTIPLE=deepseek-v4-pro
MODEL_JUDGEMENT=deepseek-flash
MODEL_COMPLETION=deepseek-flash
```

### 思考模式

DeepSeek V4 支持 thinking 和 reasoning_effort。本项目默认关闭思考，优先保证答题延迟：

```dotenv
LLM_THINKING=false
LLM_REASONING_EFFORT=high
```

难题可以打开：

```dotenv
LLM_THINKING=true
LLM_REASONING_EFFORT=high
# 开启思考后建议提高输出上限
LLM_MAX_TOKENS=4096
```

注意：

- LLM_REASONING_EFFORT 可选 low / high / max。
- 思考模式下 temperature 不生效，服务不会发送它。
- 思考模式会增加延迟，OCS 侧有 60 秒硬超时，建议先用 flash 非思考模式。
- 开启思考后如果输出被截断，服务会返回明确错误，提示提高 LLM_MAX_TOKENS。

### 图片

deepseek-flash 支持图片输入。要启用图片题：

1. OCS：通用 -> 全局设置 -> 高级设置，开启“图片题优化”。
2. 使用仓库里的 [ocs-config.json](ocs-config.json)；它会提交 images、suggestion_title、suggestion_options。
3. 服务会把 OCS 提供的 data URL 作为 image_url 内容块发给 deepseek-flash。

deepseek-v4-pro 不支持图片；如果强制用它做图片题，服务会退化为纯文本提示，模型应在信息不足时返回空答案。

### JSON 输出

默认 USE_JSON_MODE=true，请求会带 response_format={"type":"json_object"}，prompt 中也包含 JSON 示例。若遇到不支持 JSON mode 的兼容端点，服务会自动去掉该参数重试一次。

### 旧模型兼容

服务对旧 deepseek-reasoner 保留了最小化请求分支，但旧模型名已不在官方当前文档中。请优先迁移到 deepseek-flash / deepseek-v4-pro；如果使用自定义兼容端点，可通过 LLM_THINKING=false 和服务端的 400 降级逻辑提高兼容性。

## 4. 接入 OCS

1. 打开 OCS 面板：通用 -> 全局设置 -> 题库配置。
2. 把 [ocs-config.json](ocs-config.json) 的内容粘贴进去，保存并启用。
3. 回到课程页面，点“开始答题”。
4. 结果面板出现答案和蓝色“AI”标签，说明接入成功。

> ⚠️ OCS 的题库配置最外层必须是**数组**：从 `[` 到 `]` 的完整内容。只粘贴单个 `{ ... }` 会报 `Spread syntax requires ...iterable[Symbol.iterator] to be a function`。在 `/setup` 页面点“复制 JSON”可以拿到正确数组。

默认配置用 GM_xmlhttpRequest：

- 好处：绕过页面 CSP/CORS，适合 http://127.0.0.1。
- 注意：OCS 标准版的 @connect 列表可能不包含 127.0.0.1；如果请求被拦，使用“全域名通用版”，或在脚本管理器里允许该域名。

如果页面允许 fetch，也可以把配置里的 type 改成 fetch。但课程页可能有 CSP connect-src 限制，失败就换回 GM_xmlhttpRequest。

### OCS 本地缓存

OCS 会按题目标题精确匹配缓存答案，命中后不会再请求本服务。更新 prompt/模型后，老题仍可能返回旧答案；调试时到：

通用 -> 全局设置 -> 题库缓存 -> 清空缓存 / 关闭缓存

服务端缓存 key 包含题目、选项、题型、模型、站点、思考模式、图片摘要和 PROMPT_VERSION，更新 prompt 后需要同时清 OCS 缓存。

### 设置 token

如果 .env 设置了 API_TOKEN，OCS 配置的 headers 需要加：

```http
Authorization: Bearer <token>
```

也可以使用 X-API-Token 请求头。

## 5. 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /health | 健康检查，返回 provider/model/configured/thinking/vision |
| POST | /api/answer | 答题主接口 |
| GET | /api/stats | 请求量、缓存命中、错误数、平均耗时、题型分布 |
| POST | /api/cache/clear | 清空服务端缓存 |
| GET | /setup | WebUI 配置器 |
| GET | /api/config | 当前配置（API Key/Token 脱敏） |
| POST | /api/config/test | 测试 DeepSeek 连接 |
| POST | /api/config/save | 写入 .env（需重启） |
| GET | /api/ocs-config | 生成当前 OCS 题库配置 |
| GET | /docs | FastAPI 自动文档 |

配置接口默认只允许本机；设置 API_TOKEN 后需要 `Authorization: Bearer <token>`。

请求：

```json
{
  "question": "1+1=?",
  "options": ["A. 1", "B. 2"],
  "type": "single",
  "images": [],
  "site": "example.com"
}
```

成功响应：

```json
{
  "success": true,
  "ocs_format": ["1+1=?", "A", {"ai": true, "model": "deepseek-flash", "confidence": 0.95, "latency_ms": 1200, "thinking": false}],
  "answer": "A",
  "confidence": 0.95,
  "model": "deepseek-flash",
  "latency_ms": 1200,
  "cached": false,
  "request_id": "a1b2c3d4e5"
}
```

低置信度或无法校验时仍然 success=true，但 ocs_format=[]：

```json
{"success": true, "ocs_format": [], "answer": null, "confidence": 0.42, "reason": "low_confidence"}
```

业务错误（未配置 key、超时、HTTP 错误、输出截断）返回 HTTP 200 + success=false：

```json
{"success": false, "error": "DEEPSEEK_API_KEY 未配置，请在 .env 中填写后重启服务。", "ocs_format": []}
```

OCS 配置里的 handler 会把 success=false 或 detail 抛成错误，结果面板会显示错误信息；ocs_format=[] 则显示 0 个结果。

## 6. 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| HOST | 127.0.0.1 | 监听地址；自用不要改 0.0.0.0 |
| PORT | 8787 | 端口 |
| LLM_PROVIDER | deepseek | deepseek / mock |
| DEEPSEEK_API_KEY | 空 | DeepSeek key |
| DEEPSEEK_BASE_URL | https://api.deepseek.com | OpenAI 兼容 base |
| DEEPSEEK_MODEL | deepseek-flash | 默认模型 |
| MODEL_SINGLE 等 | 空 | 按题型覆盖模型 |
| LLM_THINKING | false | 是否开启思考模式 |
| LLM_REASONING_EFFORT | high | low / high / max，仅思考模式生效 |
| LLM_TIMEOUT_SECONDS | 45 | 单次模型请求超时 |
| LLM_MAX_TOKENS | 2048 | 输出上限；思考模式建议 4096+ |
| LLM_TEMPERATURE | 0 | 仅非思考模式发送 |
| USE_JSON_MODE | true | 优先 JSON mode，400 自动回退 |
| MIN_CONFIDENCE | 0.35 | 低于此值返回空 |
| API_TOKEN | 空 | 可选 Bearer token |
| DB_PATH | data/ocs_llm.db | SQLite 路径 |
| CACHE_TTL_SECONDS | 604800 | 缓存 TTL |
| CORS_ORIGINS | * | CORS；自用可保持 |
| LOG_LEVEL | INFO | 日志级别 |

## 7. 项目管理

本项目使用 pyproject.toml + uv：

```bash
uv sync                 # 安装依赖并创建/更新 .venv
uv lock                 # 重新生成 uv.lock
uv run pytest           # 跑测试
uv run python -m app    # 等价于 CLI 启动
uv build                # 构建 wheel/sdist
```

启动入口：

- uv run ocs-llm-answerer
- uv run python -m app
- uv run uvicorn app.main:app

项目结构：

```text
ocs-llm-answerer/
├── app/
│   ├── main.py              FastAPI 入口
│   ├── cli.py               ocs-llm-answerer 命令
│   ├── config.py            env 配置
│   ├── models.py            请求模型
│   ├── answer.py            选项/答案归一化与校验
│   ├── prompts.py           prompt（含图片内容块）+ LLM JSON 解析
│   ├── setup.py             WebUI 配置读写/连接测试/OCS 配置生成
│   ├── storage.py           SQLite 缓存/日志
│   ├── static/setup.html    WebUI 配置页面
│   └── providers/           DeepSeek / mock
├── tests/                   单元测试 + API/WebUI 配置测试
├── ocs-config.json          OCS 题库配置
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── .github/workflows/ci.yml
├── LICENSE
├── CONTRIBUTING.md
├── README.md
└── DEVELOPMENT.md
```

## 8. 测试

```bash
uv run pytest
```

当前 39 个用例，覆盖：选项/答案归一化、题型推断、API 主流程、缓存、图片缓存隔离、低置信度、鉴权、字符串 options、统计、DeepSeek thinking/vision payload、JSON 解析，以及 WebUI 配置读取/脱敏、保存 .env、连接测试、OCS 配置生成和本机/Token 保护。

## 9. 常见问题

| 现象 | 处理 |
|---|---|
| missing_api_key | 在 .env 填 DEEPSEEK_API_KEY，重启 |
| 服务启动失败 | 先 uv sync；确认 Python 3.12+；检查端口是否被占用 |
| OCS 显示连接失败 | 先 curl /health；确认端口、@connect、是否用了全域名通用版 |
| 请求超时 | 用 deepseek-flash；关闭 LLM_THINKING；把 LLM_TIMEOUT_SECONDS 调到 45~50 |
| 输出被截断 | 提高 LLM_MAX_TOKENS；思考模式建议 4096+ |
| 无法解析模型输出 | 确认 USE_JSON_MODE=true；提高 max_tokens；检查模型是否支持 JSON output |
| 图片题没有效果 | 开启 OCS“图片题优化”；确认模型是 deepseek-flash；清 OCS 缓存 |
| 答案对但 OCS 没点上 | 看 /api/stats 和日志；确认题型/选项文本；OCS resolver 对纯字母有兜底 |
| 填空题多空失败 | OCS 不传空数；服务从题干 ____ 推断，推断不到时只返回单段 |
| 改了 prompt 但答案没变 | 清空 OCS 题库缓存；服务端缓存可用 POST /api/cache/clear 清 |
| 401 | OCS 配置的 headers 里加 Authorization: Bearer <token>；配置页需要输入 API Token |
| 配置页 403 | 配置接口只允许本机；远程访问请先设置 API_TOKEN，并通过 token 访问 |
| OCS 解析失败：Spread syntax requires ... | 题库配置最外层必须是数组 `[...]`，不能只粘贴单个对象；重新从 /setup 复制完整 JSON |
| 保存配置后没变化 | 配置写入 .env 后需要重启服务 |
| WebUI 保存 Key 后仍显示未配置 | 看提示：若显示“已写入 .env，重启后生效”，重启即可；若仍“还没有保存”，确认 Key 输入框非空且没有勾选“清除已保存 Key” |
| 400 / 模型不存在 | 使用 deepseek-flash 或 deepseek-v4-pro；旧模型名已过时 |
| 402 | DeepSeek 余额不足，充值后重试 |

## 10. 安全

- 默认只绑 127.0.0.1，不要随意改成 0.0.0.0。
- 配置 WebUI 默认只允许本机修改；设置 API_TOKEN 后配置接口也要求 Token，防止局域网/跨站修改 .env。
- DeepSeek key 只放服务端 .env，不要写进 OCS 配置；配置页不会把已保存 Key 回传浏览器。
- 公网/局域网部署时设置 API_TOKEN，并限制防火墙/CORS。
- 课程题目和图片会发给 DeepSeek；确认数据保留策略，敏感课程慎用。
- 日志默认记录题干/选项，不记录图片 base64；注意清理和备份权限。
- 仅用于自建/授权课程或学习辅助，遵守课程平台条款。

## 11. License

MIT，见 [LICENSE](LICENSE)。欢迎 PR；开发与提交前检查见 [CONTRIBUTING.md](CONTRIBUTING.md)。

GitHub Actions 会在 push / pull request 时执行 uv sync --frozen、uv run pytest 和 CLI 版本检查。