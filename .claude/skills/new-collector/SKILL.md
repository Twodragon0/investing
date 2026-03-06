---
name: new-collector
description: 새로운 데이터 수집 스크립트를 생성합니다
user-invocable: true
disable-model-invocation: true
---

새로운 데이터 수집기 "$ARGUMENTS"를 생성합니다.

1. 기존 수집기 패턴 분석 (scripts/collect_crypto_news.py 참고)
2. scripts/common/ 공통 모듈 활용:
   - `config.py`: get_env(), setup_logging(), REQUEST_TIMEOUT
   - `dedup.py`: 중복 방지 (SHA256 해시 + fuzzy matching >80%)
   - `rss_fetcher.py`: RSS 피드 파싱
   - `crypto_api.py`: 암호화폐 API 호출
   - `post_generator.py`: Jekyll 포스트 생성
   - `image_generator.py`: 썸네일 이미지 생성
3. 새 수집기 스크립트 작성 (scripts/collect_$ARGUMENTS.py)
4. GitHub Actions 워크플로우 추가 (.github/workflows/)
5. `ruff check`으로 코드 품질 확인
6. 테스트 실행으로 동작 검증
