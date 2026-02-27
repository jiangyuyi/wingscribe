from typing import Dict, Optional
from urllib.parse import urlparse
from .provider import StorageProvider
from .local import LocalProvider

class FileSystemManager:
    _instance = None

    def __init__(self, base_dir: str):
        self.providers: Dict[str, StorageProvider] = {}

        # Initialize Local Provider with base_dir as the only allowed root
        self.local_provider = LocalProvider(base_dir=base_dir)

    @classmethod
    def get_instance(cls, base_dir: str = None):
        if cls._instance is None:
            if base_dir is None:
                raise ValueError("FileSystemManager not initialized")
            cls._instance = cls(base_dir)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """重置单例实例（用于测试或配置重新加载）"""
        cls._instance = None

    def get_provider(self, path_or_uri: str) -> StorageProvider:
        """
        Determines the correct provider for a given path/URI.
        Currently defaults to LocalProvider for all non-URI paths.
        Future: Parse smb:// or webdav:// prefixes.
        """
        # TODO: Add logic for 'smb://' or 'http://'
        return self.local_provider

    def resolve_path(self, path_or_uri: str):
        """
        Helper to get provider and relative path
        """
        provider = self.get_provider(path_or_uri)
        return provider, path_or_uri
