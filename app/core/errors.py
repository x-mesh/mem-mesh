"""
mem-mesh 통합 에러 코드 및 예외 클래스.

모든 에러는 이 모듈에서 중앙 관리합니다.
MCP JSON-RPC 에러 코드와 HTTP 상태 코드 매핑을 제공합니다.
"""


# ---------------------------------------------------------------------------
# HTTP/JSON-RPC 에러 코드 상수
# ---------------------------------------------------------------------------
class ErrorCode:
    """에러 코드 상수 (HTTP 상태 코드 매핑)"""

    # 400 Bad Request
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_CONTENT_LENGTH = "INVALID_CONTENT_LENGTH"
    INVALID_IMPORTANCE = "INVALID_IMPORTANCE"
    INVALID_STATUS_TRANSITION = "INVALID_STATUS_TRANSITION"

    # 404 Not Found
    MEMORY_NOT_FOUND = "MEMORY_NOT_FOUND"
    PIN_NOT_FOUND = "PIN_NOT_FOUND"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"
    RELATION_NOT_FOUND = "RELATION_NOT_FOUND"

    # 409 Conflict
    DUPLICATE_MEMORY = "DUPLICATE_MEMORY"
    DUPLICATE_PROMOTION = "DUPLICATE_PROMOTION"

    # 429 Too Many Requests
    TOKEN_LIMIT_EXCEEDED = "TOKEN_LIMIT_EXCEEDED"

    # 500 Internal Server Error
    DATABASE_ERROR = "DATABASE_ERROR"
    EMBEDDING_ERROR = "EMBEDDING_ERROR"
    TOKEN_ESTIMATION_ERROR = "TOKEN_ESTIMATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 에러 코드 → HTTP 상태 코드 매핑
ERROR_HTTP_STATUS = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.INVALID_CONTENT_LENGTH: 400,
    ErrorCode.INVALID_IMPORTANCE: 400,
    ErrorCode.INVALID_STATUS_TRANSITION: 400,
    ErrorCode.MEMORY_NOT_FOUND: 404,
    ErrorCode.PIN_NOT_FOUND: 404,
    ErrorCode.SESSION_NOT_FOUND: 404,
    ErrorCode.CONTEXT_NOT_FOUND: 404,
    ErrorCode.RELATION_NOT_FOUND: 404,
    ErrorCode.DUPLICATE_MEMORY: 409,
    ErrorCode.DUPLICATE_PROMOTION: 409,
    ErrorCode.TOKEN_LIMIT_EXCEEDED: 429,
    ErrorCode.DATABASE_ERROR: 500,
    ErrorCode.EMBEDDING_ERROR: 500,
    ErrorCode.TOKEN_ESTIMATION_ERROR: 500,
    ErrorCode.INTERNAL_ERROR: 500,
}

# 에러 코드 → JSON-RPC 에러 코드 매핑
ERROR_JSONRPC_CODE = {
    ErrorCode.VALIDATION_ERROR: -32602,  # Invalid params
    ErrorCode.INVALID_CONTENT_LENGTH: -32602,
    ErrorCode.INVALID_IMPORTANCE: -32602,
    ErrorCode.INVALID_STATUS_TRANSITION: -32602,
    ErrorCode.MEMORY_NOT_FOUND: -32602,
    ErrorCode.PIN_NOT_FOUND: -32602,
    ErrorCode.SESSION_NOT_FOUND: -32602,
    ErrorCode.CONTEXT_NOT_FOUND: -32602,
    ErrorCode.RELATION_NOT_FOUND: -32602,
    ErrorCode.DUPLICATE_MEMORY: -32602,
    ErrorCode.DUPLICATE_PROMOTION: -32602,
    ErrorCode.TOKEN_LIMIT_EXCEEDED: -32603,
    ErrorCode.DATABASE_ERROR: -32603,  # Internal error
    ErrorCode.EMBEDDING_ERROR: -32603,
    ErrorCode.TOKEN_ESTIMATION_ERROR: -32603,
    ErrorCode.INTERNAL_ERROR: -32603,
}


# ---------------------------------------------------------------------------
# 기본 예외 클래스
# ---------------------------------------------------------------------------
class MemMeshError(Exception):
    """mem-mesh 기본 예외"""

    error_code: str = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, **kwargs):
        self.details = kwargs
        super().__init__(message)

    @property
    def http_status(self) -> int:
        return ERROR_HTTP_STATUS.get(self.error_code, 500)

    @property
    def jsonrpc_code(self) -> int:
        return ERROR_JSONRPC_CODE.get(self.error_code, -32603)


# ---------------------------------------------------------------------------
# 404 Not Found
# ---------------------------------------------------------------------------
class MemoryNotFoundError(MemMeshError):
    error_code = ErrorCode.MEMORY_NOT_FOUND

    def __init__(self, memory_id: str):
        super().__init__(f"Memory not found: {memory_id}", memory_id=memory_id)


class PinNotFoundError(MemMeshError):
    error_code = ErrorCode.PIN_NOT_FOUND

    def __init__(self, pin_id: str):
        super().__init__(f"Pin not found: {pin_id}", pin_id=pin_id)


class SessionNotFoundError(MemMeshError):
    error_code = ErrorCode.SESSION_NOT_FOUND

    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}", session_id=session_id)


class ContextNotFoundError(MemMeshError):
    error_code = ErrorCode.CONTEXT_NOT_FOUND

    def __init__(self, memory_id: str):
        super().__init__(f"Context not found for memory: {memory_id}", memory_id=memory_id)


class RelationNotFoundError(MemMeshError):
    error_code = ErrorCode.RELATION_NOT_FOUND

    def __init__(self, source_id: str, target_id: str):
        super().__init__(
            f"Relation not found: {source_id} -> {target_id}",
            source_id=source_id,
            target_id=target_id,
        )


# ---------------------------------------------------------------------------
# 400 Bad Request
# ---------------------------------------------------------------------------
class ValidationError(MemMeshError):
    error_code = ErrorCode.VALIDATION_ERROR


class InvalidImportanceError(MemMeshError):
    error_code = ErrorCode.INVALID_IMPORTANCE

    def __init__(self, importance: int):
        super().__init__(
            f"Importance must be between 1 and 5, got {importance}",
            importance=importance,
        )


class InvalidStatusTransitionError(MemMeshError):
    error_code = ErrorCode.INVALID_STATUS_TRANSITION

    def __init__(self, current: str, target: str):
        super().__init__(
            f"Invalid status transition: {current} -> {target}",
            current_status=current,
            target_status=target,
        )


# ---------------------------------------------------------------------------
# 409 Conflict
# ---------------------------------------------------------------------------
class DuplicatePromotionError(MemMeshError):
    error_code = ErrorCode.DUPLICATE_PROMOTION

    def __init__(self, pin_id: str, memory_id: str):
        super().__init__(
            f"Pin {pin_id} is already promoted to memory {memory_id}",
            pin_id=pin_id,
            memory_id=memory_id,
        )


# ---------------------------------------------------------------------------
# 429 / 500 Server Errors
# ---------------------------------------------------------------------------
class TokenLimitExceededError(MemMeshError):
    error_code = ErrorCode.TOKEN_LIMIT_EXCEEDED

    def __init__(self, session_id: str, current_tokens: int, threshold: int):
        super().__init__(
            f"Token limit exceeded for session {session_id}: {current_tokens} > {threshold}",
            session_id=session_id,
            current_tokens=current_tokens,
            threshold=threshold,
        )


class DatabaseError(MemMeshError):
    error_code = ErrorCode.DATABASE_ERROR


class EmbeddingError(MemMeshError):
    error_code = ErrorCode.EMBEDDING_ERROR


class TokenEstimationError(MemMeshError):
    error_code = ErrorCode.TOKEN_ESTIMATION_ERROR

    def __init__(self, content_length: int, original_error: Exception):
        super().__init__(
            f"Failed to estimate tokens for content of length {content_length}: {original_error}",
            content_length=content_length,
        )
