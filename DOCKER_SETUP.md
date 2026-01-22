# mem-mesh Docker 설정 완료

## 작업 내용

### 생성된 파일
1. **Dockerfile** - 프로덕션용 멀티 스테이지 빌드
2. **Dockerfile.dev** - 개발용 이미지 (hot-reload, 디버깅 도구 포함)
3. **.dockerignore** - Docker 빌드 최적화
4. **docker-compose.yml** - 프로덕션/개발 환경 오케스트레이션
5. **Makefile** - 편리한 Docker 명령어 래퍼

### 주요 기능

#### Dockerfile 특징
- Python 3.11 slim 베이스 이미지
- 멀티 스테이지 빌드로 이미지 크기 최적화
- 비root 사용자(memmesh) 실행
- Health check 내장
- 데이터 영속성 지원 (./data, ./logs)

#### Makefile 명령어
```bash
make build-dev      # 개발 이미지 빌드
make up-dev         # 개발 컨테이너 시작
make bash-dev       # 컨테이너 bash 접속
make logs-dev       # 로그 확인
make test           # 테스트 실행
make health         # 상태 확인
make down           # 컨테이너 중지
make clean          # 정리
```

### 테스트 결과

✅ 개발 이미지 빌드 성공
✅ 컨테이너 실행 성공
✅ 애플리케이션 임포트 성공
✅ 웹 서버 시작 성공 (http://localhost:8000)
✅ API 헬스체크 성공 (/api/health)
✅ Bash 접속 가능
✅ 데이터 볼륨 마운트 확인

### 사용 예시

```bash
# 빠른 시작
make build-dev && make up-dev

# 로그 확인
make logs-dev

# 컨테이너 접속하여 디버깅
make bash-dev

# 컨테이너 내부에서
python -m app.web --reload
python -m pytest tests/ -v
python -c "from app.web.app import app"

# 정리
make down
```

### README 업데이트

Docker 섹션이 README.md에 추가되었습니다:
- 빠른 시작 가이드
- 주요 명령어 설명
- Docker Compose 직접 사용법
- 디버깅 방법
- 데이터 영속성 설명

## 다음 단계

1. 프로덕션 이미지 테스트
2. CI/CD 파이프라인 통합
3. Docker Hub 또는 레지스트리에 이미지 푸시
4. Kubernetes 배포 매니페스트 작성 (선택사항)

## 참고사항

- 개발 환경은 hot-reload가 활성화되어 있어 코드 변경 시 자동 재시작
- 데이터는 호스트의 ./data 디렉토리에 영속적으로 저장
- 컨테이너는 8000(웹), 8001(MCP) 포트를 노출
- libsqlite3-dev 패키지가 pysqlite3 빌드를 위해 필요
