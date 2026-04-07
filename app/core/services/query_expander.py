"""
Query Expander - 한국어/영어 검색어 확장
검색 품질 향상을 위한 쿼리 확장 모듈
"""

import re
from typing import Dict, List, Optional, Tuple

KOREAN_TIME_EXPRESSIONS: Dict[str, str] = {
    "오늘": "today",
    "어제": "yesterday",
    "이번주": "this_week",
    "이번 주": "this_week",
    "지난주": "last_week",
    "지난 주": "last_week",
    "이번달": "this_month",
    "이번 달": "this_month",
    "지난달": "last_month",
    "지난 달": "last_month",
    "이번분기": "this_quarter",
    "이번 분기": "this_quarter",
}

ENGLISH_TIME_EXPRESSIONS: Dict[str, str] = {
    "today": "today",
    "yesterday": "yesterday",
    "this week": "this_week",
    "last week": "last_week",
    "this month": "this_month",
    "last month": "last_month",
    "this quarter": "this_quarter",
}


def extract_time_expression(query: str) -> Tuple[Optional[str], str]:
    """쿼리에서 시간 표현을 추출하고 제거된 쿼리를 반환.

    Args:
        query: 원본 쿼리 문자열

    Returns:
        (time_range, cleaned_query) 튜플.
        time_range가 None이면 시간 표현이 감지되지 않은 것.
    """
    lower = query.strip()

    # Korean time expressions (sorted by length descending — longer patterns first)
    for expr in sorted(KOREAN_TIME_EXPRESSIONS, key=len, reverse=True):
        if expr in lower:
            time_range = KOREAN_TIME_EXPRESSIONS[expr]
            cleaned = lower.replace(expr, "").strip()
            # Keep original if remaining query is empty
            return (time_range, cleaned if cleaned else query)

    # English time expressions
    for expr in sorted(ENGLISH_TIME_EXPRESSIONS, key=len, reverse=True):
        if expr in lower.lower():
            time_range = ENGLISH_TIME_EXPRESSIONS[expr]
            # Remove case-insensitively
            cleaned = re.sub(re.escape(expr), "", lower, flags=re.IGNORECASE).strip()
            return (time_range, cleaned if cleaned else query)

    return (None, query)


class QueryExpander:
    """검색어 확장 클래스"""

    def __init__(self):
        """Initialize query expander with translation dictionaries"""
        # Korean → English key term dictionary
        self.kr_to_en = {
            "토큰": "token",
            "최적화": "optimization optimize",
            "검색": "search",
            "품질": "quality",
            "캐시": "cache",
            "캐싱": "caching",
            "메모리": "memory",
            "배치": "batch",
            "임베딩": "embedding embed",
            "벡터": "vector",
            "의도": "intent",
            "점수": "score",
            "피드백": "feedback",
            "성능": "performance",
            "속도": "speed",
            "버그": "bug",
            "수정": "fix",
            "개선": "improve improvement",
            "향상": "enhance enhancement",
            "저장": "save storage",
            "로드": "load",
            "분석": "analyze analysis",
            "테스트": "test testing",
            "결과": "result",
            "문제": "problem issue",
            "해결": "solve solution",
            "방법": "method way",
            "시스템": "system",
            "서비스": "service",
            "프로젝트": "project",
            "코드": "code",
            "파일": "file",
            "데이터": "data",
            "데이터베이스": "database db",
            "쿼리": "query",
            "응답": "response",
            "요청": "request",
            "처리": "process processing",
            "관리": "manage management",
            "설정": "config configuration setting",
            "도구": "tool",
            "통합": "integrate integration",
            "구현": "implement implementation",
            "전략": "strategy",
            "패턴": "pattern",
            "모델": "model",
            "학습": "learn learning training",
            "예측": "predict prediction",
            "분류": "classify classification",
            "카테고리": "category",
            "태그": "tag",
            "필터": "filter",
            "정렬": "sort sorting",
            "인덱스": "index",
            "스키마": "schema",
            "타입": "type",
            "에러": "error",
            "경고": "warning",
            "로그": "log logging",
            "디버그": "debug debugging",
            "추적": "trace tracking tracing",
            "모니터링": "monitor monitoring",
            "메트릭": "metric metrics",
            "통계": "statistics stats",
            "차트": "chart",
            "그래프": "graph",
            "대시보드": "dashboard",
            "인터페이스": "interface",
            "사용자": "user",
            "클라이언트": "client",
            "서버": "server",
            "네트워크": "network",
            "연결": "connect connection",
            "세션": "session",
            "상태": "state status",
            "업데이트": "update",
            "삭제": "delete remove",
            "추가": "add create",
            "변경": "change modify",
            "복사": "copy",
            "이동": "move",
            "백업": "backup",
            "복원": "restore",
            "초기화": "init initialize",
            "시작": "start begin",
            "종료": "end stop finish",
            "재시작": "restart",
            "실행": "run execute",
            "빌드": "build",
            "컴파일": "compile",
            "배포": "deploy deployment",
            "설치": "install",
            "제거": "uninstall remove",
            "업그레이드": "upgrade",
            "다운그레이드": "downgrade",
            "버전": "version",
            "릴리즈": "release",
            "패치": "patch",
            "핫픽스": "hotfix",
            "롤백": "rollback",
            "마이그레이션": "migration migrate",
            "동기화": "sync synchronize",
            "비동기": "async asynchronous",
            "병렬": "parallel",
            "직렬": "serial sequential",
            "큐": "queue",
            "스택": "stack",
            "리스트": "list",
            "배열": "array",
            "맵": "map",
            "딕셔너리": "dictionary dict",
            "세트": "set",
            "트리": "tree",
            "노드": "node",
            "엣지": "edge",
            "경로": "path route",
            "알고리즘": "algorithm",
            "함수": "function",
            "메소드": "method",
            "클래스": "class",
            "객체": "object",
            "인스턴스": "instance",
            "속성": "property attribute",
            "변수": "variable",
            "상수": "constant const",
            "파라미터": "parameter param",
            "인자": "argument arg",
            "반환": "return",
            "예외": "exception",
            "핸들러": "handler",
            "이벤트": "event",
            "콜백": "callback",
            "프로미스": "promise",
            "테스크": "task",
            "작업": "job work task",
            "스레드": "thread",
            "프로세스": "process",
            "메모리릭": "memory leak",
            "가비지컬렉션": "garbage collection gc",
            "캐시히트": "cache hit",
            "캐시미스": "cache miss",
            "레이턴시": "latency",
            "처리량": "throughput",
            "병목": "bottleneck",
            "최적": "optimal",
            "효율": "efficient efficiency",
            "비용": "cost",
            "절감": "reduce reduction save",
            "증가": "increase",
            "감소": "decrease",
            "향상된": "enhanced improved",
            "스마트": "smart intelligent",
            "자동": "auto automatic",
            "수동": "manual",
            "커스텀": "custom",
            "디폴트": "default",
            "옵션": "option",
            "설정값": "setting value config",
            "환경변수": "environment variable env",
            "키": "key",
            "값": "value",
            "페어": "pair",
            "튜플": "tuple",
            "레코드": "record",
            "로우": "row",
            "컬럼": "column",
            "테이블": "table",
            "뷰": "view",
            "트리거": "trigger",
            "프로시저": "procedure",
            "펑션": "function",
            "트랜잭션": "transaction",
            "커밋": "commit",
            "락": "lock",
            "데드락": "deadlock",
            "동시성": "concurrency concurrent",
            "원자성": "atomicity atomic",
            "일관성": "consistency consistent",
            "격리": "isolation",
            "지속성": "durability",
            "무결성": "integrity",
            "보안": "security secure",
            "인증": "authentication auth",
            "권한": "authorization permission",
            "액세스": "access",
            "쿠키": "cookie",
            "헤더": "header",
            "바디": "body",
            "페이로드": "payload",
            "상태코드": "status code",
            "리다이렉트": "redirect",
            "프록시": "proxy",
            "게이트웨이": "gateway",
            "로드밸런서": "load balancer",
            "클러스터": "cluster",
            "파드": "pod",
            "컨테이너": "container",
            "도커": "docker",
            "쿠버네티스": "kubernetes k8s",
            "마이크로서비스": "microservice",
            "모놀리식": "monolithic",
            "서버리스": "serverless",
            "클라우드": "cloud",
            "온프레미스": "on-premise",
            "하이브리드": "hybrid",
            "스케일": "scale",
            "스케일업": "scale up",
            "스케일아웃": "scale out",
            "탄력성": "elasticity elastic",
            "가용성": "availability",
            "신뢰성": "reliability reliable",
            "내구성": "durability durable",
            "복구": "recovery recover",
            "스냅샷": "snapshot",
            "체크포인트": "checkpoint",
            "복제": "replication replicate",
            "미러링": "mirroring mirror",
            "샤딩": "sharding shard",
            "파티셔닝": "partitioning partition",
            "인덱싱": "indexing",
            "해싱": "hashing hash",
            "암호화": "encryption encrypt",
            "복호화": "decryption decrypt",
            "해시": "hash",
            "솔트": "salt",
            "인증서": "certificate cert",
            "서명": "signature sign",
            "검증": "validation verify",
            "단위테스트": "unit test",
            "통합테스트": "integration test",
            "엔드투엔드": "end to end e2e",
            "회귀테스트": "regression test",
            "성능테스트": "performance test",
            "부하테스트": "load test",
            "스트레스테스트": "stress test",
            "벤치마크": "benchmark",
            "프로파일링": "profiling profile",
            "디버깅": "debugging debug",
            "로깅": "logging log",
            "알람": "alarm alert",
            "노티피케이션": "notification notify",
            "리포트": "report",
            "지표": "indicator kpi",
            "트렌드": "trend",
            "이상": "anomaly abnormal",
            "정상": "normal",
            "임계값": "threshold",
            "한계": "limit",
            "제한": "restriction limit",
            "할당량": "quota",
            "용량": "capacity",
            "크기": "size",
            "길이": "length",
            "너비": "width",
            "높이": "height",
            "깊이": "depth",
            "차원": "dimension",
            "행렬": "matrix",
            "텐서": "tensor",
            "스칼라": "scalar",
            "그래디언트": "gradient",
            "역전파": "backpropagation backprop",
            "순전파": "forward propagation",
            "신경망": "neural network",
            "딥러닝": "deep learning",
            "머신러닝": "machine learning ml",
            "인공지능": "artificial intelligence ai",
            "자연어처리": "natural language processing nlp",
            "컴퓨터비전": "computer vision cv",
            "추천시스템": "recommendation system recommender",
            "분류기": "classifier",
            "회귀": "regression",
            "클러스터링": "clustering",
            "차원축소": "dimensionality reduction",
            "특징추출": "feature extraction",
            "전처리": "preprocessing preprocess",
            "정규화": "normalization normalize regularization regularize",
            "표준화": "standardization standardize",
            "인코딩": "encoding encode",
            "디코딩": "decoding decode",
            "토큰화": "tokenization tokenize",
            "벡터화": "vectorization vectorize",
            "어텐션": "attention",
            "트랜스포머": "transformer",
            "컨볼루션": "convolution convolutional cnn",
            "리커런트": "recurrent rnn",
            "장단기기억": "lstm long short term memory",
            "게이트": "gate gated",
            "활성화": "activation activate",
            "드롭아웃": "dropout",
            "배치정규화": "batch normalization",
            "레이어정규화": "layer normalization",
            "가중치": "weight",
            "편향": "bias",
            "손실": "loss",
            "정확도": "accuracy",
            "정밀도": "precision",
            "재현율": "recall",
            "에프원": "f1 score",
            "혼동행렬": "confusion matrix",
            "교차검증": "cross validation",
            "과적합": "overfitting overfit",
            "과소적합": "underfitting underfit",
            "조기종료": "early stopping",
            "학습률": "learning rate",
            "배치크기": "batch size",
            "에폭": "epoch",
            "반복": "iteration iterate",
            "스텝": "step",
            "옵티마이저": "optimizer",
            "모멘텀": "momentum",
            "아담": "adam",
            "경사하강법": "gradient descent sgd",
            "미분": "differentiation derivative",
            "적분": "integration integral",
            "행렬곱": "matrix multiplication matmul",
            "내적": "dot product",
            "외적": "cross product",
            "노름": "norm",
            "거리": "distance",
            "유사도": "similarity",
            "코사인유사도": "cosine similarity",
            "유클리드거리": "euclidean distance",
            "맨하탄거리": "manhattan distance",
            "해밍거리": "hamming distance",
            "편집거리": "edit distance levenshtein",
            "자카드유사도": "jaccard similarity",
            "피어슨상관계수": "pearson correlation",
            "스피어만상관계수": "spearman correlation",
            "켄달타우": "kendall tau",
            "엔트로피": "entropy",
            "정보이득": "information gain",
            "지니계수": "gini index coefficient",
            "실루엣점수": "silhouette score",
            "데이비스볼딘": "davies bouldin",
            "칼린스키하라바스": "calinski harabasz",
            "아이크": "aic akaike",
            "비아이씨": "bic bayesian",
            "알스퀘어": "r squared r2",
            "평균제곱오차": "mean squared error mse",
            "평균절대오차": "mean absolute error mae",
            "루트평균제곱오차": "root mean squared error rmse",
            "평균절대백분율오차": "mean absolute percentage error mape",
            "로그손실": "log loss",
            "교차엔트로피": "cross entropy",
            "쿨백라이블러": "kullback leibler kl divergence",
            "와서스테인거리": "wasserstein distance",
            "젠센섀넌": "jensen shannon",
            "민코프스키거리": "minkowski distance",
            "체비셰프거리": "chebyshev distance",
            "마할라노비스거리": "mahalanobis distance",
            "브레그만발산": "bregman divergence",
            "총변동거리": "total variation distance",
        }

        # Generate English → Korean reverse dictionary
        self.en_to_kr = {}
        for kr, en_terms in self.kr_to_en.items():
            for en_term in en_terms.split():
                if en_term not in self.en_to_kr:
                    self.en_to_kr[en_term] = []
                self.en_to_kr[en_term].append(kr)

    def expand_query(self, query: str) -> str:
        """
        검색어를 확장하여 한국어/영어 모두 포함

        Args:
            query: 원본 검색어

        Returns:
            확장된 검색어
        """
        # Preserve original
        original = query.lower()
        expanded_terms = set([original])

        # Split by spaces
        words = original.split()

        for word in words:
            # Korean → English
            if word in self.kr_to_en:
                en_terms = self.kr_to_en[word].split()
                expanded_terms.update(en_terms)

            # English → Korean
            if word in self.en_to_kr:
                kr_terms = self.en_to_kr[word]
                expanded_terms.update(kr_terms)

            # Also try partial matching
            for kr, en in self.kr_to_en.items():
                if kr in word or word in kr:
                    expanded_terms.add(kr)
                    expanded_terms.update(en.split())

        # Remove duplicates and join with spaces
        expanded = " ".join(sorted(expanded_terms))

        # If too long, keep original and main translations only
        if len(expanded) > 200:
            main_terms = [original]
            for word in words[:3]:  # First 3 words only
                if word in self.kr_to_en:
                    main_terms.append(self.kr_to_en[word].split()[0])
                elif word in self.en_to_kr:
                    main_terms.append(self.en_to_kr[word][0])
            expanded = " ".join(main_terms)

        return expanded

    def is_korean(self, text: str) -> bool:
        """텍스트가 한국어인지 확인"""
        korean_pattern = re.compile("[가-힣]+")
        return bool(korean_pattern.search(text))

    def is_english(self, text: str) -> bool:
        """텍스트가 영어인지 확인"""
        english_pattern = re.compile("[a-zA-Z]+")
        return bool(english_pattern.search(text))

    def get_language(self, text: str) -> str:
        """텍스트의 주 언어 판별"""
        korean_count = len(re.findall("[가-힣]", text))
        english_count = len(re.findall("[a-zA-Z]", text))

        if korean_count > english_count:
            return "korean"
        elif english_count > korean_count:
            return "english"
        else:
            return "mixed"

    def suggest_terms(self, query: str) -> List[str]:
        """연관 검색어 제안"""
        suggestions = []
        words = query.lower().split()

        for word in words:
            # Suggest English if Korean
            if word in self.kr_to_en:
                en_terms = self.kr_to_en[word].split()
                suggestions.extend(en_terms)

            # Suggest Korean if English
            if word in self.en_to_kr:
                kr_terms = self.en_to_kr[word]
                suggestions.extend(kr_terms)

        return list(set(suggestions))[:5]  # Max 5


# Singleton instance
_query_expander = None


def get_query_expander() -> QueryExpander:
    """Get singleton QueryExpander instance"""
    global _query_expander
    if _query_expander is None:
        _query_expander = QueryExpander()
    return _query_expander
