from src.recognition.protocol import ListPlatformsResponse, PlatformInfo


DEFAULT_PLATFORM = "local"


def build_platforms_response(default_platform: str = DEFAULT_PLATFORM) -> ListPlatformsResponse:
    return ListPlatformsResponse(
        platforms=[
            PlatformInfo(
                id="local",
                name="本地 BioCLIP",
                description="使用本地部署的 BioCLIP 模型进行识别",
                requires_api_key=False,
                is_cloud=False,
            ),
            PlatformInfo(
                id="huggingface",
                name="HuggingFace",
                description="通过 HuggingFace Inference API 调用云端模型",
                requires_api_key=True,
                is_cloud=True,
                max_image_size_mb=10,
            ),
            PlatformInfo(
                id="modelscope",
                name="魔搭社区",
                description="通过魔搭社区 API-Inference 调用云端模型",
                requires_api_key=True,
                is_cloud=True,
            ),
            PlatformInfo(
                id="dongniao",
                name="懂鸟",
                description="国内专业鸟类识别 API 服务",
                requires_api_key=True,
                is_cloud=True,
                supported_formats=["jpg", "jpeg", "png", "webp"],
                max_image_size_mb=10,
            ),
            PlatformInfo(
                id="aliyun",
                name="阿里云视觉智能",
                description="阿里云图像标签识别服务",
                requires_api_key=True,
                is_cloud=True,
            ),
            PlatformInfo(
                id="baidu",
                name="百度智能云",
                description="百度云图像识别服务",
                requires_api_key=True,
                is_cloud=True,
            ),
        ],
        default_platform=default_platform,
    )
