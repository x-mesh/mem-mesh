"""
Context Token Optimization 에러 클래스

Requirements: 전체
"""


class TokenLimitExceededError(Exception):
    """토큰 사용량이 임계값을 초과했을 때 발생하는 에러"""
    
    def __init__(self, session_id: str, current_tokens: int, threshold: int):
        self.session_id = session_id
        self.current_tokens = current_tokens
        self.threshold = threshold
        super().__init__(
            f"Token limit exceeded for session {session_id}: "
            f"{current_tokens} > {threshold}"
        )


class InvalidImportanceError(ValueError):
    """importance 값이 1-5 범위를 벗어났을 때 발생하는 에러"""
    
    def __init__(self, importance: int):
        self.importance = importance
        super().__init__(
            f"Importance must be between 1 and 5, got {importance}"
        )


class PinNotFoundError(Exception):
    """핀을 찾을 수 없을 때 발생하는 에러"""
    
    def __init__(self, pin_id: str):
        self.pin_id = pin_id
        super().__init__(f"Pin not found: {pin_id}")


class SessionNotFoundError(Exception):
    """세션을 찾을 수 없을 때 발생하는 에러"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class DuplicatePromotionError(Exception):
    """이미 승격된 핀을 다시 승격하려고 할 때 발생하는 에러
    
    Note: 현재 구현에서는 중복 승격을 에러로 처리하지 않고
    기존 memory_id를 반환하므로 이 에러는 사용되지 않습니다.
    """
    
    def __init__(self, pin_id: str, memory_id: str):
        self.pin_id = pin_id
        self.memory_id = memory_id
        super().__init__(
            f"Pin {pin_id} is already promoted to memory {memory_id}"
        )


class TokenEstimationError(Exception):
    """토큰 수 계산 실패 시 발생하는 에러"""
    
    def __init__(self, content_length: int, original_error: Exception):
        self.content_length = content_length
        self.original_error = original_error
        super().__init__(
            f"Failed to estimate tokens for content of length {content_length}: "
            f"{str(original_error)}"
        )
