# K-TEST

**AI 기반 외국인 노동자 한국어 직무 소통 능력 평가 플랫폼**

K-TEST는 외국인 노동자의 실제 직무 현장에서 필요한 한국어 소통 능력을
AI 기반으로 평가하는 플랫폼입니다.

## 팀원 및 역할

| 이름 | 역할 | 담당 영역 |
| --- | --- | --- |
| 한효주 | 프론트엔드 | `apps/web` (Next.js) |
| 백예나 | 백엔드 | `apps/api` (NestJS) |
| 전재완 | AI 채점 | `services/scoring` (Python) |
| 김도영 | 부정행위 감지 | `services/proctoring` (Python) |
| 양은희 | 디자인 | `assets` (문항 삽화 등) |
| — | 공용 | `packages/shared` (공용 타입 정의) |

> 팀원 6명이 각 영역을 담당합니다.

## 폴더 구조

```
K-TEST/
├── apps/
│   ├── web/          # 프론트엔드 (Next.js) — 한효주
│   └── api/          # 백엔드 (NestJS) — 백예나
├── services/
│   ├── scoring/      # AI 채점 파이프라인 (Python) — 전재완
│   └── proctoring/   # 부정행위 감지 (Python) — 김도영
├── packages/
│   └── shared/       # 프론트·백엔드 공용 타입 정의
└── assets/           # 문항 삽화 등 디자인 에셋 — 양은희
```

## 브랜치 규칙

- `main` 브랜치에 **직접 push 금지**
- 모든 작업은 **기능 브랜치**에서 진행하고 **PR(Pull Request)로 머지**
- PR은 **리뷰어 1명 이상의 승인** 후 머지
