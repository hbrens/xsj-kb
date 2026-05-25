# xsj-kb

新视界鸿蒙知识库。

## 结构

- `data/` — 数据源，按数据集分目录存放
- `sync/` — 数据同步脚本（Hash 比对 → RAGFlow API）
- `mcp/` — MCP 审计网关
- `skill/` — Skill 相关

## 数据集

| 目录 | 内容 |
|------|------|
| `01_xsj-internal-guides` | 团队规范、FAQ、踩坑记录 |
| `02_deveco-sdk-api` | DevEco SDK API |
| `03_project-code` | 项目代码、组件库 |
| `04_harmonyos-docs` | HarmonyOS 官方文档 |
| `05_openharmony-docs` | OpenHarmony 开源文档 |
| `06_harmonyos-samples` | 官方样例代码 |

## 常用命令

```bash
uv sync                          # 创建虚拟环境并安装依赖（venv 在 .venv/ 下）
uv run python mcp/server/server.py  # 启动 MCP 网关（默认 self-host，读取 .env 中的 API key）
```
