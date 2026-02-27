---
name: fix-issue
description: GitHub 이슈를 분석하고 수정합니다
disable-model-invocation: true
---

GitHub 이슈 $ARGUMENTS를 분석하고 수정합니다.

1. `gh issue view $ARGUMENTS`으로 이슈 상세 확인
2. 관련 파일을 코드베이스에서 검색
3. 문제의 근본 원인 분석
4. 수정 사항 구현
5. `python3 -m ruff check scripts/`로 린트 확인
6. 설명적인 커밋 메시지 작성 (한국어)
7. PR 생성
