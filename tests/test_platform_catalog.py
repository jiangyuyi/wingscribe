from src.recognition.platform_catalog import build_platforms_response


def test_build_platforms_response_returns_shared_platform_metadata():
    response = build_platforms_response()

    assert response.default_platform == "local"
    assert [platform.id for platform in response.platforms] == [
        "local",
        "huggingface",
        "modelscope",
        "dongniao",
        "aliyun",
        "baidu",
    ]
    assert response.platforms[1].requires_api_key is True
    assert response.platforms[1].max_image_size_mb == 10
    assert response.platforms[3].supported_formats == ["jpg", "jpeg", "png", "webp"]
