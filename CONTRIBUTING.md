# Contributing

感谢你愿意改进 OCS LLM Answerer。

## 本地开发

~~~bash
uv sync
cp .env.example .env
uv run ocs-llm-answerer --reload
~~~

打开 http://127.0.0.1:8787/setup 可以配置和测试连接。没有 DeepSeek Key 时：

~~~bash
LLM_PROVIDER=mock uv run ocs-llm-answerer
~~~

## 提交前检查

~~~bash
uv run pytest
uv lock --check
uv build
~~~

## 约定

- 不要提交 .env、API Key、SQLite 数据或本地缓存；
- 新增配置项时同步更新 .env.example、app/config.py、WebUI 和文档；
- 修改 DeepSeek 请求参数时先核对官方文档，并补 provider 测试；
- 配置接口必须保持“本机或 API Token”保护，不能暴露已保存的 Key；
- 提交信息建议使用 Conventional Commits，例如 `feat: add webui setup page`。

## License

MIT，见 [LICENSE](LICENSE)。
