# B8 本地协议维护

2026-10-25。B7 双变体隔离安装/升级/卸载已验证，干净虚拟机按用户要求保留方案、暂不安装。下一批仅处理本地可验证的协议维护，不升级依赖、不联调云端、不调整产品决策。

## B8a：Pydantic 配置及 API 文档

1. 将识别协议中五个旧式 `class Config` 换为 Pydantic 2 的 `ConfigDict`，保持请求字段、约束、默认值和响应格式。
2. 修复 `BatchResultResponse` 文档样例中的 Python `Ellipsis`，补齐样例必填字段。现已复现 `json.dumps(model_json_schema())` 因 Ellipsis 失败；普通模型 schema 构造成功不能证明 OpenAPI 可序列化。
3. 对所有带例子的协议模型验证样例可作为 JSON、可通过各自模型校验；测试识别路由的真实 `/openapi.json`，并运行现有服务/路由契约回归。全程不加载真实模型或调用云端。
4. 验证后提交并记录边界，再决定后续维护项，不把警告消除当作线上云端验证。

依据：[Pydantic 2 配置迁移](https://docs.pydantic.dev/latest/migration/#changes-to-config)。
