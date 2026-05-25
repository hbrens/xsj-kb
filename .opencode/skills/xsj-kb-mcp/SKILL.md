---
name: xsj-kb-mcp
description: 当用户询问鸿蒙、HarmonyOS、OpenHarmony、ArkTS、ArkUI、DevEco、SDK API、官方样例、项目代码模式或团队内部鸿蒙规范时，使用 xsj-kb MCP 检索知识库后再回答。
---

# xsj-kb MCP 使用指南

本 skill 用来指导 agent 何时使用 `xsj-kb` MCP，以及如何高质量检索新视界鸿蒙知识库。

## 先决判断

遇到以下情况时，优先调用 `xsj-kb` MCP，不要只凭模型记忆回答：

- 用户询问 HarmonyOS、OpenHarmony、鸿蒙应用开发、ArkTS、ArkUI、Ability、Stage 模型、窗口、路由、状态管理、权限、签名、打包、调试、发布等平台相关问题。
- 用户询问 DevEco、SDK API、组件用法、系统能力、错误码、编译构建、Hvigor、module.json5、oh-package、HAR/HSP 等鸿蒙工程问题。
- 用户需要官方文档、官方样例、内部规范、项目代码里的实现方式或最佳实践。
- 用户问“项目里怎么写”“团队规范是什么”“有没有示例”“这个 API 怎么用”“报错怎么处理”等需要从知识库验证的内容。
- 用户给出类名、函数名、装饰器、配置字段、错误码、日志关键字，需要精确查找来源。

以下情况通常不需要调用：

- 与鸿蒙/OpenHarmony/新视界项目知识库无关的一般编程问题。
- 用户明确要求不要检索 MCP。
- 纯代码格式化、翻译、简单文字润色，且不涉及知识正确性。

## MCP 配置

项目的 `opencode.json` 注册了远程 MCP：

```json
{
  "mcp": {
    "xsj-kb": {
      "type": "remote",
      "url": "http://127.0.0.1:9382/mcp"
    }
  }
}
```

OpenCode 暴露 MCP 工具时通常会加上服务器名前缀。实际可用工具名一般是：

- `xsj-kb_ragflow_retrieval`

服务端内部工具名是：

- `ragflow_retrieval`

如果工具列表里显示的名称不同，以当前会话的可用 MCP 工具名为准。

## 可检索内容

知识库按数据源组织，实际 `dataset_ids` 由 MCP 动态返回。不要编造数据集 ID；只有在工具描述或前一次结果里看到了真实 ID，才传入 `dataset_ids`。

常见数据源包括：

| 来源目录 | 内容 |
| --- | --- |
| `01_xsj-internal-guides` | 团队规范、FAQ、踩坑记录 |
| `02_deveco-sdk-api` | DevEco SDK API |
| `03_project-code` | 项目代码、组件库 |
| `04_harmonyos-docs` | HarmonyOS 官方文档 |
| `05_openharmony-docs` | OpenHarmony 开源文档 |
| `06_harmonyos-samples` | 官方样例代码 |

## 检索策略

默认先全库检索，也就是不传 `dataset_ids` 或传空数组，让 MCP 自动搜索所有可访问数据集。

构造 `question` 时要保留用户原始关键词，并补充同义技术词。例如用户问“页面状态刷新”，可以检索：

```json
{
  "question": "HarmonyOS ArkUI 页面状态刷新 @State @Link @Prop 状态管理"
}
```

精确查找类名、方法名、装饰器、配置字段、错误码时，启用关键词检索：

```json
{
  "question": "AbilityStage onCreate",
  "keyword": true,
  "similarity_threshold": 0.35
}
```

需要更完整的背景时，提高 `page_size` 到 `20` 或 `30`。不要一开始就拉很大的结果集，除非用户明确要求全面调研。

如果首次结果不够好，换一种 query 再查一次，而不是直接下结论。常用改写方式：

- 中文问题加英文 API 名。
- 错误现象加日志关键字。
- 业务说法加 HarmonyOS/OpenHarmony 官方术语。
- “怎么做”类问题拆成 API 用法、工程配置、样例代码三个方向。

## 参数参考

`ragflow_retrieval` 支持这些参数：

- `question`: 必填，检索问题。
- `dataset_ids`: 可选，真实数据集 ID 数组；未知时不要传。
- `document_ids`: 可选，真实文档 ID 数组。
- `page`: 可选，默认 `1`。
- `page_size`: 可选，默认 `10`，建议 `10-30`。
- `similarity_threshold`: 可选，默认 `0.2`；精确问题可调到 `0.35-0.6`。
- `vector_similarity_weight`: 可选，默认 `0.3`；概念类问题可适当提高，精确标识符查找可保持默认或降低。
- `keyword`: 可选，默认 `false`；查 API 名、类名、字段名、错误码时设为 `true`。
- `top_k`: 可选，默认 `1024`。
- `rerank_id`: 可选，通常不需要传。
- `force_refresh`: 可选，默认 `false`；只有用户明确要求最新元数据，或你怀疑文档元数据缓存过期时才设为 `true`。

## 回答规则

使用 MCP 结果回答时：

- 优先综合多个高相关 chunk，不要机械拼接。
- 明确区分“文档明确说明”和“基于结果推断”。
- 如果结果包含 `dataset_name`、`document_name`、`document_metadata.name` 等来源信息，回答中简短标注来源。
- 如果检索结果不足、互相矛盾或没有命中，直接说明没有在 xsj-kb 中找到可靠依据，并给出下一步建议或需要用户补充的关键词。
- 不要编造不存在的 API、参数、数据集 ID、文档名或来源。

## 建议流程

1. 判断问题是否属于鸿蒙/OpenHarmony/项目知识库范围。
2. 选择一个具体 `question` 调用 `xsj-kb_ragflow_retrieval`。
3. 对 API 名、错误码、配置字段类问题设置 `keyword: true`。
4. 结果不足时最多再改写检索 1-2 次。
5. 基于检索结果给出简洁、可执行的答案，并标注关键来源。
