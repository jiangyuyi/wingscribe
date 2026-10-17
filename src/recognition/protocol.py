"""
统一识别接口协议定义

定义所有识别平台（本地、云平台）通用的请求/响应格式，
支持单张识别、批量识别、异步回调等场景。
"""
from enum import Enum
from typing import List, Optional, Literal
from pydantic import BaseModel, Field, model_validator
from datetime import datetime


class RecognitionPlatform(str, Enum):
    """支持的识别平台"""
    local = "local"
    huggingface = "huggingface"
    modelscope = "modelscope"
    aliyun = "aliyun"
    baidu = "baidu"
    dongniao = "dongniao"  # 懂鸟 API
    custom = "custom"


class ImageSourceType(str, Enum):
    """图片来源类型"""
    path = "path"       # 本地文件路径
    url = "url"         # 图片 URL
    base64 = "base64"   # Base64 编码


class RecognitionResult(BaseModel):
    """单个识别结果"""
    label: str = Field(..., description="物种标签（原始返回）")
    scientific_name: Optional[str] = Field(None, description="学名")
    chinese_name: Optional[str] = Field(None, description="中文名")
    confidence: float = Field(..., ge=0, le=1, description="置信度 0-1")
    source_label: Optional[str] = Field(None, description="原始平台返回的标签")


class RecognizeRequest(BaseModel):
    """单张图片识别请求"""
    # 图片来源（三选一）
    image_path: Optional[str] = Field(None, description="本地文件路径")
    image_url: Optional[str] = Field(None, description="图片 URL")
    image_base64: Optional[str] = Field(None, description="Base64 编码图片数据")

    # 识别配置
    platform: RecognitionPlatform = Field(..., description="识别平台")
    top_k: int = Field(5, ge=1, le=20, description="返回前 K 个结果")
    timeout: int = Field(60, ge=1, le=300, description="超时时间（秒）")

    # 区域过滤（可选）
    region_filter: Optional[Literal["china", "global", "auto"]] = Field(
        None, description="区域过滤"
    )

    @model_validator(mode="after")
    def require_one_image_source(self):
        values = (self.image_path, self.image_url, self.image_base64)
        if sum(value is not None for value in values) != 1 or not any(value and value.strip() for value in values):
            raise ValueError("Provide exactly one non-empty image source")
        return self

    class Config:
        json_schema_extra = {
            "example": {
                "image_path": "/path/to/bird.jpg",
                "platform": "huggingface",
                "top_k": 5,
                "timeout": 60
            }
        }


class RecognizeResponse(BaseModel):
    """单张图片识别响应"""
    success: bool = Field(..., description="是否成功")
    image_path: Optional[str] = Field(None, description="原始图片路径")
    image_url: Optional[str] = Field(None, description="图片 URL")
    results: List[RecognitionResult] = Field(default_factory=list, description="识别结果列表")
    platform: str = Field(..., description="实际使用的平台")
    processing_time_ms: int = Field(..., description="处理耗时（毫秒）")
    error: Optional[str] = Field(None, description="错误信息")

    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "image_path": "/path/to/bird.jpg",
                "results": [
                    {
                        "label": "Great Tit",
                        "scientific_name": "Parus major",
                        "chinese_name": "大山雀",
                        "confidence": 0.95
                    }
                ],
                "platform": "huggingface",
                "processing_time_ms": 1250
            }
        }


class BatchJobStatus(str, Enum):
    """批量任务状态"""
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class BatchJobItem(BaseModel):
    """批量任务中的单个项目"""
    request: RecognizeRequest
    response: Optional[RecognizeResponse] = None
    status: BatchJobStatus = Field(default=BatchJobStatus.pending)
    error: Optional[str] = None


class BatchRecognizeRequest(BaseModel):
    """批量识别请求"""
    images: List[RecognizeRequest] = Field(..., min_length=1, max_length=1000)
    batch_id: Optional[str] = Field(None, description="批次 ID，不提供则自动生成")
    webhook_url: Optional[str] = Field(None, description="完成后回调地址")
    notify_email: Optional[str] = Field(None, description="完成后通知邮箱")

    class Config:
        json_schema_extra = {
            "example": {
                "images": [
                    {"image_path": "/path/to/bird1.jpg", "platform": "huggingface"},
                    {"image_path": "/path/to/bird2.jpg", "platform": "local"}
                ],
                "webhook_url": "https://example.com/callback"
            }
        }


class BatchRecognizeResponse(BaseModel):
    """批量识别响应"""
    batch_id: str = Field(..., description="批次 ID")
    total: int = Field(..., description="总图片数")
    completed: int = Field(default=0, description="已完成数")
    failed: int = Field(default=0, description="失败数")
    status: BatchJobStatus = Field(..., description="任务状态")
    progress_percent: float = Field(default=0.0, description="完成进度百分比")
    webhook_url: Optional[str] = Field(None, description="回调地址")
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "batch_abc123",
                "total": 10,
                "completed": 5,
                "failed": 0,
                "status": "processing",
                "progress_percent": 50.0
            }
        }


class BatchResultItem(BaseModel):
    """批量任务单项结果"""
    index: int = Field(..., description="原始索引")
    image_path: Optional[str] = None
    success: bool
    result: Optional[RecognizeResponse] = None
    error: Optional[str] = None


class BatchResultResponse(BaseModel):
    """批量任务完整结果"""
    batch_id: str
    status: BatchJobStatus
    total: int
    results: List[BatchResultItem]
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        json_schema_extra = {
            "example": {
                "batch_id": "batch_abc123",
                "status": "completed",
                "total": 10,
                "results": [
                    {
                        "index": 0,
                        "image_path": "/path/to/bird1.jpg",
                        "success": True,
                        "result": {"success": True, "results": [...], "processing_time_ms": 1250}
                    }
                ]
            }
        }


class PlatformInfo(BaseModel):
    """平台信息"""
    id: str
    name: str
    description: str
    requires_api_key: bool = False
    supported_formats: List[str] = ["jpg", "jpeg", "png"]
    max_image_size_mb: float = 4.0
    is_cloud: bool = False


class ListPlatformsResponse(BaseModel):
    """平台列表响应"""
    platforms: List[PlatformInfo]
    default_platform: str = "local"


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = "healthy"
    version: str
    platform: str
    gpu_available: bool
    gpu_device: Optional[str] = None
    models_loaded: List[str] = []
