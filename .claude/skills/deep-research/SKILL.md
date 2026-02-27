---
name: deep-research
description: 코드베이스를 심층 분석합니다
context: fork
agent: Explore
---

"$ARGUMENTS" 주제를 심층적으로 조사합니다.

1. Glob과 Grep으로 관련 파일 찾기
2. 코드를 읽고 패턴 분석
3. 의존성과 호출 관계 추적
4. 발견 사항을 구체적인 파일 참조와 함께 요약

조사 범위:
- scripts/ (Python 수집/생성 스크립트)
- .github/workflows/ (CI/CD 파이프라인)
- _layouts/, _includes/ (Jekyll 템플릿)
- _posts/ (생성된 포스트)
