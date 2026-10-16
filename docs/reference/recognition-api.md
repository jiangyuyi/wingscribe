# 识别 API 与云配置

核对日期：2026-10-16；依据本地路由、协议和工厂代码。没有执行付费/远程调用，不保证第三方服务端点当前可用。

## 两种服务入口

| 入口 | 启动命令 | 路由 |
| --- | --- | --- |
| 完整 Web 应用 | `python src/web/app.py` | `/api/recognition/recognize`、`/api/recognition/batch`、批次查询/结果/取消、`/api/recognition/platforms`、`/api/recognition/health` |
| 独立识别服务 | `python src/recognition_service.py` | `/api/recognize`、`/platforms`、`/health`；没有挂载 Web 批量路由 |

从仓库根目录启动；两者默认使用配置中的同一端口，不要同时占用同一地址。启动后 `/docs` 展示对应入口的实际 OpenAPI。

## 请求协议

`RecognizeRequest` 使用 `platform`、`top_k`（1–20，默认 5）、`timeout`（1–300 秒，默认 60），图片字段为 `image_path`、`image_url` 或 `image_base64`。调用者应只提供一种图片来源；协议模型并未强制“三选一”。`image_path` 是服务端可访问的路径，不是客户端文件上传。

```json
{
  "image_path": "D:/Photos/sample.jpg",
  "platform": "huggingface",
  "top_k": 5,
  "timeout": 60
}
```

此处只展示请求结构，需先配置并验证对应平台。批量请求为 `{"images": [上述请求对象]}`，最多 1000 项，可提供 `webhook_url`。创建后查询 `/api/recognition/batch/{batch_id}` 和 `/api/recognition/batch/{batch_id}/result`；任务状态在内存中，不应当作持久任务队列。

## 云适配器配置

`settings.yaml` 与 `secrets.yaml` 递归合并。统一 REST 云适配器读取以下路径：

| 平台 | `config/secrets.yaml` 字段 |
| --- | --- |
| HuggingFace | `cloud.huggingface.api_token`、可选 `model_id` |
| ModelScope | `cloud.modelscope.api_token`、可选 `model_id` |
| 阿里云 | `cloud.aliyun.access_key_id`、`access_key_secret` |
| 百度 | `cloud.baidu.api_key`、`secret_key` |

旧文档的 `HF_TOKEN` 等环境变量示例不对应这些适配器的实际配置读取；使用上述 YAML 字段。平台是否能真正识别，还取决于账号、服务端点、模型接口和适配逻辑，不能仅凭文件存在认定已联调。

## 流水线是另一条配置路径

`src/pipeline_runner.py` 只处理 `recognition.mode: local/api/dongniao`。`api` 读取 `recognition.api.key` 和 `.url`，懂鸟读取 `recognition.dongniao.key` 和 `.url`，可放在 secrets 中递归合并。顶层 `hf_api_key`、`dongniao_api_key` 不会自动转成这两个配置。

统一 REST 工厂中的 `local` 与 `dongniao` 仍返回旧式 `predict/predict_batch` 识别器，未适配路由期待的 `recognize()`；`custom` 虽在枚举中，却未注册。不要将这些值作为已可用的 REST 示例。

## 部署限制

API Key 检查当前直接放行，独立服务也未实现有效访问认证。旧方案中的 Docker Compose、鉴权中间件和远程识别流水线不能直接照抄部署：仓库没有完整落地这些能力。需要对外服务时先处理 [已知问题](../development/status.md)。
