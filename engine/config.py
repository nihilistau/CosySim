"""
Configuration Manager for CosyVoice System

Loads and merges configuration from:
1. config/default.yaml (base)
2. config/{environment}.yaml (environment-specific overrides)
3. Environment variables (runtime overrides)

Usage:
    from engine.config import ConfigManager
    
    config = ConfigManager()
    db_path = config.get("database.sqlite.path")
    port = config.get("scenes.phone.port", default=5555)
"""

import os
import yaml
from pathlib import Path
from typing import Any, Optional, Dict
import logging

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages system configuration with environment-based overrides."""
    
    def __init__(self, environment: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            environment: Environment name (development, production, etc.)
                        If None, uses COSYVOICE_ENV environment variable or "default"
        """
        self.environment = environment or os.getenv("COSYVOICE_ENV", "default")
        self.config_dir = Path(__file__).parent.parent / "config"
        self._config: Dict[str, Any] = {}
        
        self._load_config()
    
    def _load_config(self) -> None:
        """Load and merge configuration files."""
        # 1. Load default configuration
        default_config = self._load_yaml(self.config_dir / "default.yaml")
        if not default_config:
            raise RuntimeError("Default configuration not found!")
        
        self._config = default_config
        
        # 2. Load environment-specific configuration
        if self.environment != "default":
            env_config_path = self.config_dir / f"{self.environment}.yaml"
            if env_config_path.exists():
                env_config = self._load_yaml(env_config_path)
                self._config = self._deep_merge(self._config, env_config)
                logger.info(f"Loaded {self.environment} configuration")
            else:
                logger.warning(f"Environment config not found: {env_config_path}")
        
        # 3. Override with environment variables
        self._apply_env_overrides()
        
        logger.info(f"Configuration loaded (environment: {self.environment})")
    
    def _load_yaml(self, path: Path) -> Optional[Dict[str, Any]]:
        """Load YAML file."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load {path}: {e}")
            return None
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides."""
        # Map environment variables to config paths
        env_mappings = {
            "COSYVOICE_DB_PATH": "database.sqlite.path",
            "COSYVOICE_PHONE_PORT": "scenes.phone.port",
            "COSYVOICE_DASHBOARD_PORT": "scenes.dashboard.port",
            "COSYVOICE_LLM_URL": "llm.base_url",
            "COSYVOICE_LLM_MODEL": "llm.model",
            "COSYVOICE_TTS_DEVICE": "tts.device",
            "COSYVOICE_STT_DEVICE": "stt.device",
            "COSYVOICE_LOG_LEVEL": "logging.level",
        }
        
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                self.set(config_path, value)
                logger.debug(f"Override from {env_var}: {config_path} = {value}")
    
    def get(self, path: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation path.
        
        Args:
            path: Dot-notation path (e.g., "database.sqlite.path")
            default: Default value if path not found
        
        Returns:
            Configuration value or default
        
        Example:
            >>> config = ConfigManager()
            >>> config.get("database.sqlite.path")
            'simulation.db'
            >>> config.get("nonexistent.key", "default_value")
            'default_value'
        """
        keys = path.split(".")
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    def set(self, path: str, value: Any) -> None:
        """
        Set configuration value by dot-notation path.
        
        Args:
            path: Dot-notation path (e.g., "database.sqlite.path")
            value: Value to set
        
        Example:
            >>> config = ConfigManager()
            >>> config.set("database.sqlite.path", "/tmp/test.db")
        """
        keys = path.split(".")
        target = self._config
        
        for key in keys[:-1]:
            if key not in target:
                target[key] = {}
            target = target[key]
        
        target[keys[-1]] = value
    
    def get_all(self) -> Dict[str, Any]:
        """
        Get entire configuration dictionary.
        
        Returns:
            Complete configuration
        """
        return self._config.copy()
    
    def reload(self) -> None:
        """Reload configuration from files."""
        self._config = {}
        self._load_config()
        logger.info("Configuration reloaded")
    
    def __repr__(self) -> str:
        return f"<ConfigManager environment={self.environment}>"


# Global config instance
_config_instance: Optional[ConfigManager] = None


def get_config() -> ConfigManager:
    """
    Get global configuration instance.
    
    Returns:
        ConfigManager singleton instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigManager()
    return _config_instance


def reload_config() -> None:
    """Reload global configuration."""
    global _config_instance
    if _config_instance is not None:
        _config_instance.reload()
    else:
        _config_instance = ConfigManager()
