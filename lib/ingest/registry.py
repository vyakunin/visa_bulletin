"""Plugin registry for data source plugins"""

from typing import Optional
from .base import DataSourcePlugin
from models.ingest.enums import DataDomain, SourceType


class PluginRegistry:
    """Central registry for data source plugins"""
    
    _plugins: dict[str, DataSourcePlugin] = {}
    
    @classmethod
    def register(cls, plugin: DataSourcePlugin):
        """
        Register a plugin.
        
        Args:
            plugin: Plugin instance to register
        """
        if not isinstance(plugin.domain, DataDomain):
            raise ValueError(f"Plugin domain must be DataDomain enum, got {type(plugin.domain)}")
        if not isinstance(plugin.source_type, SourceType):
            raise ValueError(f"Plugin source_type must be SourceType enum, got {type(plugin.source_type)}")
        
        key = f"{plugin.domain.value}:{plugin.source_type.value}"
        cls._plugins[key] = plugin
    
    @classmethod
    def get_plugin(cls, domain: str | DataDomain, source_type: str | SourceType) -> Optional[DataSourcePlugin]:
        """
        Get plugin by domain and source type.
        
        Args:
            domain: Domain string or enum
            source_type: Source type string or enum
            
        Returns:
            Plugin instance or None if not found
        """
        # Normalize to string values
        domain_val = domain.value if hasattr(domain, 'value') else domain
        source_val = source_type.value if hasattr(source_type, 'value') else source_type
        key = f"{domain_val}:{source_val}"
        return cls._plugins.get(key)
    
    @classmethod
    def list_plugins(cls) -> list[tuple[str, str, DataSourcePlugin]]:
        """
        List all registered plugins.
        
        Returns:
            List of (domain, source_type, plugin) tuples
        """
        return [
            (key.split(':')[0], key.split(':')[1], plugin)
            for key, plugin in cls._plugins.items()
        ]
    
    @classmethod
    def clear(cls):
        """Clear all registered plugins (mainly for testing)"""
        cls._plugins.clear()










