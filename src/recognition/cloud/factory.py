"""
识别器工厂模块

根据配置和请求创建对应的识别器实例。
"""
from typing import Dict, Type, Optional, Any
from ..base import AbstractBirdRecognizer
from ..protocol import RecognitionPlatform
from .huggingface import HuggingFaceRecognizer
from .modelscope import ModelScopeRecognizer
from .aliyun import AliyunRecognizer
from .baidu import BaiduRecognizer
from ..inference_dongniao import DongniaoRecognizer
from ...utils.config_loader import get_config
import logging

logger = logging.getLogger(__name__)


class RecognizerFactory:
    """识别器工厂"""

    # 平台到识别器类的映射
    _recognizers: Dict[str, Type[AbstractBirdRecognizer]] = {
        RecognitionPlatform.huggingface.value: HuggingFaceRecognizer,
        RecognitionPlatform.modelscope.value: ModelScopeRecognizer,
        RecognitionPlatform.aliyun.value: AliyunRecognizer,
        RecognitionPlatform.baidu.value: BaiduRecognizer,
        "dongniao": DongniaoRecognizer,  # 懂鸟 API
    }

    @classmethod
    def create(
        cls,
        platform: str,
        **kwargs
    ) -> AbstractBirdRecognizer:
        """
        创建识别器实例

        Args:
            platform: 平台标识符
            **kwargs: 额外的初始化参数

        Returns:
            识别器实例

        Raises:
            ValueError: 未知平台
            RuntimeError: 识别器不可用
        """
        if platform not in cls._recognizers:
            # 如果是本地识别，尝试加载本地识别器
            if platform == RecognitionPlatform.local.value:
                from ..inference_local import LocalBirdRecognizer
                # 从配置中获取 hf_mirror 参数
                config = get_config()
                rec_config = config.get('recognition', {})
                hf_mirror = rec_config.get('hf_mirror')
                # 合并 kwargs 和 hf_mirror
                create_kwargs = {**kwargs, 'hf_mirror': hf_mirror}
                return LocalBirdRecognizer(**create_kwargs)
            raise ValueError(f"Unknown platform: {platform}")

        recognizer_class = cls._recognizers[platform]

        # 尝试创建实例
        try:
            recognizer = recognizer_class(**kwargs)

            # 检查是否可用
            if hasattr(recognizer, 'is_available') and not recognizer.is_available:
                raise RuntimeError(f"{platform} recognizer is not available. Please check API keys.")

            return recognizer

        except ValueError as e:
            logger.error(f"Failed to create {platform} recognizer: {e}")
            raise
        except Exception as e:
            logger.error(f"Error creating {platform} recognizer: {e}")
            raise RuntimeError(f"Failed to initialize {platform} recognizer: {e}")

    @classmethod
    def create_from_request(cls, request) -> AbstractBirdRecognizer:
        """从请求对象创建识别器"""
        platform = request.platform.value if hasattr(request.platform, 'value') else request.platform
        return cls.create(platform)

    @classmethod
    def register(cls, platform: str, recognizer_class: Type[AbstractBirdRecognizer]):
        """注册新的识别器"""
        cls._recognizers[platform] = recognizer_class
        logger.info(f"Registered recognizer for platform: {platform}")

    @classmethod
    def get_available_platforms(cls) -> list:
        """获取可用的平台列表"""
        available = []
        for platform, recognizer_class in cls._recognizers.items():
            try:
                recognizer = recognizer_class()
                if recognizer.is_available:
                    available.append(platform)
            except Exception:
                continue
        return available

    @classmethod
    def get_all_platforms(cls) -> list:
        """获取所有已注册的平台"""
        return list(cls._recognizers.keys())


def get_default_config() -> Dict[str, Any]:
    """获取各平台的默认配置"""
    config = get_config()
    cloud_config = config.get("cloud", {})

    return {
        "huggingface": {
            "api_token": cloud_config.get("huggingface", {}).get("api_token"),
            "model_id": cloud_config.get("huggingface", {}).get("model_id"),
        },
        "modelscope": {
            "api_token": cloud_config.get("modelscope", {}).get("api_token"),
            "model_id": cloud_config.get("modelscope", {}).get("model_id"),
        },
        "aliyun": {
            "access_key_id": cloud_config.get("aliyun", {}).get("access_key_id"),
            "access_key_secret": cloud_config.get("aliyun", {}).get("access_key_secret"),
        },
        "baidu": {
            "api_key": cloud_config.get("baidu", {}).get("api_key"),
            "secret_key": cloud_config.get("baidu", {}).get("secret_key"),
        },
    }
