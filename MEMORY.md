# MEMORY Loop Guide

## Purpose

이 문서는 OpenClaw + OpenCode 개선 루프의 장기 기억 축을 정의합니다.

## Hourly Loop Contract

- Scheduler: `.github/workflows/continuous-improvement-loop.yml` (`0 * * * *`)
- Sync step: `bash /Users/namyongkim/Desktop/.twodragon0/bin/hourly-opencode-git-pull.sh`
- Execution order: Ralph -> Ultrawork -> `scripts/continuous_improvement_loop.py`
- Evidence location: `_state/continuous-improvement-loop.md`, `_state/continuous-improvement-loop-slack.txt`, `_state/continuous-improvement-roles/*.txt`

## Memory Domains

- 운영(ops): CI/CD 안정성, 배포 건강도, 재시도/에스컬레이션 상태
- 보안(security): 의존성 취약점, 시크릿 위생, 알림 트리아지
- 모니터링(monitoring): 반복 실패 원인, 감지/알림 경로, 장애 대응 속도
- 성능(performance): 워크플로우 실행 시간, 캐시 효율, API 사용량
- 코드 품질(code-quality): lint/type/test 회귀 및 유지보수성
- 콘텐츠 품질(content-quality): 중복/신뢰도/요약 품질
- UI/UX(uiux): 반응형 렌더링, 가독성, 레이아웃 안정성
- 디자인(design): 비주얼 일관성, 생성 이미지 품질

## Operating Rules

- 매 실행에서 P0/P1 우선순위를 다시 계산하고 Slack 메시지에 반영
- 무한 루프 금지: 각 실행은 단일 사이클로 종료
- 상태 파일 `_state/*.json`은 수정하지 않고 읽기 전용으로 사용
