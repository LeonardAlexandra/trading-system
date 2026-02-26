import os
import yaml
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

def load_config(config_path: str = None) -> Dict[str, Any]:
    """
    加载配置（支持环境变量和 YAML 文件）
    
    优先级：环境变量 > YAML 文件 > 默认值
    """
    # 加载 .env 文件
    load_dotenv()
    
    # 确定配置文件路径
    if config_path is None:
        config_path = os.getenv(
            "CONFIG_PATH",
            str(Path(__file__).parent.parent.parent / "config" / "config.yaml")
        )
    
    # 加载 YAML 配置
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    
    # 环境变量覆盖（支持 ${VAR_NAME} 格式的变量替换）
    config = _resolve_env_vars(config)
    
    # 应用环境变量覆盖
    config = _apply_env_overrides(config)
    
    return config

def _resolve_env_vars(config: Dict[str, Any]) -> Dict[str, Any]:
    """解析配置中的环境变量引用（${VAR_NAME} 格式）"""
    if isinstance(config, dict):
        return {k: _resolve_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [_resolve_env_vars(item) for item in config]
    elif isinstance(config, str) and config.startswith("${") and config.endswith("}"):
        var_name = config[2:-1]
        return os.getenv(var_name, config)
    else:
        return config

def _apply_env_overrides(config: Dict[str, Any]) -> Dict[str, Any]:
    """应用环境变量覆盖"""
    # 数据库配置（Postgres 必须为 postgresql+asyncpg://user:pass@host:5432/dbname）
    if "DATABASE_URL" in os.environ:
        if "database" not in config:
            config["database"] = {}
        config["database"]["url"] = os.getenv("DATABASE_URL")
    
    # TradingView 配置
    if "TV_WEBHOOK_SECRET" in os.environ:
        if "tradingview" not in config:
            config["tradingview"] = {}
        config["tradingview"]["webhook_secret"] = os.getenv("TV_WEBHOOK_SECRET")
    
    # 交易所配置
    if "EXCHANGE_NAME" in os.environ:
        if "exchange" not in config:
            config["exchange"] = {}
        config["exchange"]["name"] = os.getenv("EXCHANGE_NAME")
    
    if "EXCHANGE_SANDBOX" in os.environ:
        if "exchange" not in config:
            config["exchange"] = {}
        config["exchange"]["sandbox"] = os.getenv("EXCHANGE_SANDBOX", "true").lower() == "true"
    
    if "EXCHANGE_API_KEY" in os.environ:
        if "exchange" not in config:
            config["exchange"] = {}
        config["exchange"]["api_key"] = os.getenv("EXCHANGE_API_KEY")
    
    if "EXCHANGE_API_SECRET" in os.environ:
        if "exchange" not in config:
            config["exchange"] = {}
        config["exchange"]["api_secret"] = os.getenv("EXCHANGE_API_SECRET")
    
    if "PRODUCT_TYPE" in os.environ:
        config["product_type"] = os.getenv("PRODUCT_TYPE")
    
    # 策略配置（测试/部署可覆盖）
    if "STRATEGY_ID" in os.environ:
        if "strategy" not in config:
            config["strategy"] = {}
        config["strategy"]["strategy_id"] = os.getenv("STRATEGY_ID")
    
    # 日志配置
    if "LOG_LEVEL" in os.environ:
        if "logging" not in config:
            config["logging"] = {}
        config["logging"]["level"] = os.getenv("LOG_LEVEL")
    
    if "LOG_FILE" in os.environ:
        if "logging" not in config:
            config["logging"] = {}
        config["logging"]["file"] = os.getenv("LOG_FILE")
    
    if "LOG_DATABASE" in os.environ:
        if "logging" not in config:
            config["logging"] = {}
        config["logging"]["database"] = os.getenv("LOG_DATABASE", "false").lower() == "true"
    
    return config
