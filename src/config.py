"""
Configuration module for mem-mesh server.

This module provides configuration management using pydantic-settings
with support for environment variables and .env file loading.
"""

from typing import Optional
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Application settings with environment variable support.
    
    All settings can be overridden via environment variables with MEM_MESH_ prefix.
    For example: MEM_MESH_DATABASE_PATH=/custom/path/db.sqlite
    """
    
    # Database configuration (Requirements 6.2, 6.3)
    database_path: str = Field(
        default="./data/memories.db",
        description="Path to SQLite database file"
    )
    
    # Embedding configuration (Requirements 6.4, 6.5)
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-transformers model name"
    )
    embedding_dim: int = Field(
        default=384,
        description="Embedding vector dimensions"
    )
    
    # Search configuration (Requirements 6.6)
    search_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for search results"
    )
    
    # Logging configuration (Requirements 6.7)
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    
    # Server configuration (Requirements 6.8)
    server_host: str = Field(
        default="127.0.0.1",
        description="Server host address"
    )
    server_port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Server port number"
    )
    
    # Performance settings
    max_content_length: int = Field(
        default=10000,
        ge=1,
        description="Maximum content length in characters"
    )
    min_content_length: int = Field(
        default=10,
        ge=1,
        description="Minimum content length in characters"
    )
    
    # Retry configuration
    max_embedding_retries: int = Field(
        default=3,
        ge=1,
        description="Maximum retries for embedding generation"
    )
    embedding_retry_delay: float = Field(
        default=0.1,
        ge=0.0,
        description="Base delay between embedding retries in seconds"
    )
    
    @validator("log_level")
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is one of the standard levels."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v.upper()
    
    @validator("min_content_length", "max_content_length")
    def validate_content_lengths(cls, v: int, values: dict) -> int:
        """Validate content length constraints."""
        if "min_content_length" in values and v < values["min_content_length"]:
            raise ValueError("max_content_length must be >= min_content_length")
        return v
    
    @validator("embedding_model")
    def validate_embedding_model(cls, v: str) -> str:
        """Validate embedding model name is not empty."""
        if not v.strip():
            raise ValueError("embedding_model cannot be empty")
        return v.strip()
    
    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        env_prefix = "MEM_MESH_"
        case_sensitive = False
        validate_assignment = True


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """
    Get the global settings instance.
    
    This function provides dependency injection support for FastAPI
    and allows for easy testing with different configurations.
    
    Returns:
        Settings: The global settings instance
    """
    return settings


def reload_settings() -> Settings:
    """
    Reload settings from environment and .env file.
    
    This is useful for testing or when configuration changes at runtime.
    
    Returns:
        Settings: New settings instance with reloaded values
    """
    global settings
    settings = Settings()
    return settings