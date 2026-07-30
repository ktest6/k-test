# K-TEST Backend

온라인 시험 플랫폼 백엔드. NestJS + TypeScript + Supabase(Database/Storage), Clean Architecture 기반 모듈형 구조로 구성되어 있습니다. Prisma는 사용하지 않으며, `@supabase/supabase-js`를 통해 데이터 접근을 Repository 패턴으로 캡슐화합니다.

## 기술 스택

- NestJS, TypeScript
- Supabase (Database, Storage) — `@supabase/supabase-js`. 인증은 Supabase Auth(GoTrue)를 쓰지 않고 자체 발급 JWT(`@nestjs/jwt`) + bcrypt로 처리합니다 (아래 Auth 섹션 참고).
- Swagger (`@nestjs/swagger`)
- ESLint + Prettier
- Docker

## 시작하기

```bash
npm install
cp .env.example .env   # Supabase 프로젝트 URL/키 등을 채워넣기
```

Supabase 프로젝트에 스키마 적용 (Supabase CLI 사용 시):

```bash
supabase link --project-ref <project-ref>
supabase db push
```

또는 `supabase/migrations/0001_init.sql`, `0002_user_registration_fields.sql`, `0003_convert_timestamps_to_timestamptz.sql`을 순서대로 Supabase SQL Editor에 직접 붙여넣어 실행해도 됩니다.

로컬 개발 서버 실행:

```bash
npm run start:dev
```

기동 후 `http://localhost:3000/docs`에서 Swagger UI로 전체 API(Auth/User/Identity Verification/Exam/Question/Submission/Scoring/AI, 8개 태그)를 확인할 수 있습니다.

### 자주 쓰는 명령어

| 명령어 | 설명 |
| --- | --- |
| `npm run start:dev` | watch 모드로 개발 서버 실행 |
| `npm run build` | `dist/`로 빌드 |
| `npm run lint` | ESLint 검사 및 자동 수정 |
| `npm run format` | Prettier 포맷팅 |
| `npm run test` | 단위 테스트 (Jest) |
| `npm run test:e2e` | e2e 테스트 |
| `npm run test:cov` | 커버리지 포함 단위 테스트 |

### Docker

```bash
docker compose up --build
```

Supabase는 관리형 클라우드 서비스 사용을 전제로 하며, `docker-compose.yml`은 앱 컨테이너만 정의합니다. 완전한 로컬 환경이 필요하면 별도로 [Supabase CLI](https://supabase.com/docs/guides/cli)의 `supabase start`를 사용하세요.

## 아키텍처

각 도메인은 `src/modules/<name>/` 아래에서 Clean Architecture 4계층으로 분리되어 있습니다.

```
modules/<name>/
├── domain/           # 엔티티, enum, Repository 인터페이스(Port) — 프레임워크 비의존
├── application/       # DTO, Use-case 서비스 — Port에만 의존
├── infrastructure/     # Supabase 기반 Repository 구현체, 외부 provider 어댑터
└── presentation/       # 컨트롤러, Swagger 문서
```

기본 모듈: `auth`, `user`, `identity-verification`, `exam`, `question`, `submission`, `scoring`, `ai`.

### 공통 응답 형식 (Response Envelope)

프론트로 나가는 모든 응답은 성공/에러 관계없이 같은 필드 구조를 갖습니다:

```jsonc
// 성공
{
  "success": true,
  "statusCode": 200,
  "message": "OK",
  "data": { /* 실제 payload */ },
  "path": "/users/me",
  "timestamp": "2026-07-30T12:00:00.000Z"
}

// 에러
{
  "success": false,
  "statusCode": 404,
  "message": "User 1 not found",
  "data": null,
  "code": "NOT_FOUND",
  "path": "/users/1",
  "timestamp": "2026-07-30T12:00:00.000Z"
}
```

- 컨트롤러는 지금까지처럼 순수 DTO만 리턴하면 됩니다 — `TransformResponseInterceptor`(전역, `APP_INTERCEPTOR`)가 성공 응답을 자동으로 위 봉투에 담습니다. 204(No Content) 응답은 HTTP 스펙상 바디가 없어야 하므로 감싸지 않고 그대로 통과시킵니다.
- 에러는 `HttpExceptionFilter`가 같은 모양으로 내보냅니다. `code`는 `DomainException`(및 하위 클래스: `NotFoundDomainException`, `ForbiddenDomainException`, `ConflictDomainException`, `UnauthorizedDomainException`)이 지정한 값이거나, 일반 `HttpException`이면 `HTTP_ERROR`, 그 외 예기치 못한 에러면 `INTERNAL_ERROR`입니다.
- 기본 성공 메시지는 상태 코드 기준(`200`→"OK", `201`→"Created")이며, 라우트별로 다른 메시지가 필요하면 컨트롤러 메서드에 `@ResponseMessage('로그인 성공')`을 붙이면 됩니다.
- Swagger 문서에도 이 봉투가 그대로 반영됩니다. 각 엔드포인트는 실제 응답 DTO 대신 `@ApiStandardResponse(ResponseDto, { status?, isArray? })`를 붙이며, 이 데코레이터가 봉투 스키마(`ApiSuccessResponseDto`)와 실제 DTO 스키마를 `allOf`로 합성해서 `data` 필드 안에 정확한 타입을 보여줍니다. 공통 에러 응답(400/401/403/404/500)은 컨트롤러 단위로 `@ApiCommonErrorResponses()`를 붙여서 문서화합니다.

### Auth (응시자 회원가입 / 로그인)

Supabase Auth(GoTrue)는 사용하지 않고, `tb_user` 테이블 기반의 자체 인증을 구현합니다: 비밀번호는 `UserService`에서 bcrypt로 해시해 `tb_user.password`에 저장하고, 로그인 성공 시 `AuthService`가 access/refresh 토큰을 직접 서명합니다(`@nestjs/jwt`, 시크릿/만료시간은 `JWT_ACCESS_SECRET`/`JWT_REFRESH_SECRET` 등 env로 분리). `JwtAuthGuard`는 매 요청마다 이 토큰을 검증할 뿐 DB를 조회하지 않습니다 — `role`을 포함한 사용자 정보는 토큰 발급 시점의 값이 그대로 클레임에 담기므로, 역할이 바뀌면 재로그인 전까지는 반영되지 않는다는 트레이드오프가 있습니다.

**항목 최소화 원칙**: 계정(이메일/비밀번호) + 응시 당일 신분증 대조에 필요한 최소 신원 정보만 수집합니다. `(id_type, id_number)` 조합에 유니크 제약(`uq_user_identity_document`)을 걸어 동일인이 여러 계정을 만드는 것을 막습니다.

**가입 플로우** (프론트엔드 단계 ↔ 백엔드 API):

| 단계 | 화면 | API |
| --- | --- | --- |
| 1 | 이메일/비밀번호 입력 | — |
| 2 | 이메일 중복 확인 | `GET /auth/check-email?email=` |
| 3 | 인적사항 입력 (영문성명/국적/생년월일/신분증종류+번호/기업코드) | — |
| 4 | 약관 동의 (이용약관, 개인정보처리방침 — 둘 다 필수) | — |
| 5 | 가입 완료 (위 정보를 한 번에 전송) | `POST /auth/sign-up` |

`POST /auth/sign-up`은 이메일 중복과 `(id_type, id_number)` 중복을 서버에서 다시 검증한 뒤(경쟁 상태 대비) `tb_user`에 삽입하고, 약관 동의 시각(`terms_agreed_at`, `privacy_agreed_at`)을 서버 타임스탬프로 기록합니다. 약관 동의 필드(`agreedToTerms`, `agreedToPrivacyPolicy`)는 `true`가 아니면 검증 단계에서 거부됩니다.

**엔드포인트**: `GET /auth/check-email`, `POST /auth/sign-up`, `POST /auth/sign-in`, `POST /auth/refresh`, `POST /auth/sign-out`(stateless라 서버는 아무 것도 하지 않음 — 클라이언트가 토큰 폐기), `GET /auth/me`.

**관리자 계정 생성** (`POST /auth/admin/sign-up`): `tb_user`가 응시자/관리자를 같은 테이블로 관리하므로(`role` 컬럼으로 구분), 응시자 전용 필드(국적/생년월일/신분증/약관동의)는 관리자 계정에 아예 없다 — 마이그레이션 `0004_admin_user_fields_nullable.sql`에서 해당 컬럼을 nullable로 바꾸고, `role = 'ADMIN' OR (모든 응시자 필드 NOT NULL)`을 CHECK 제약으로 강제해 응시자 쪽은 여전히 필수임을 DB 레벨에서 보장한다. 이 엔드포인트는 `@Public()`(로그인 불필요)이지만 서버 env `ADMIN_SIGNUP_SECRET`과 일치하는 `adminSecret`을 요구한다 — 로그인한 관리자만 새 관리자를 만들 수 있게 하면 "첫 관리자를 누가 만드나"라는 부트스트랩 문제가 생기기 때문에, 공유 비밀값으로 게이트를 걸었다. 비밀값 비교는 `timingSafeEqual`로 처리(타이밍 공격 방지).

### Identity Verification (본인인증)

가장 핵심적인 모듈로, 다음을 지원합니다:

- **사전 인증**: `POST /identity-verification/pre-exam/initiate` → `verify`
- **응시 중 재인증**: `GET /identity-verification/periodic/status`로 클라이언트가 폴링하면 서버가 계산한 `nextCheckAt`(다음 재인증 시점)과 `dueNow` 여부를 반환. `dueNow`가 true면 `POST /identity-verification/periodic/verify` 호출.
- **결과/로그 저장**: `identity_verification_sessions`(인증 컨텍스트) → `identity_verification_attempts`(개별 시도, N:1) → `identity_verification_logs`(세부 감사 트레일, attempt 1건당 N개 로그 가능)로 3단계 저장.
- **실패 시 확장 가능한 처리**: `VerificationFailurePolicy` 인터페이스가 연속 실패 횟수를 `NONE`/`WARNING`/`DISQUALIFICATION`으로 매핑합니다(`DefaultVerificationFailurePolicy`, 임계값은 `IDENTITY_VERIFICATION_MAX_FAILURES_BEFORE_DISQUALIFICATION`으로 설정). 실제 인증 수단은 `IdentityProvider` 포트로 추상화되어 있으며 현재는 `MockIdentityProviderAdapter`가 스텁으로 동작합니다 — 향후 PASS/NICE, 얼굴 인식 등 실제 provider로 교체 가능합니다. Mock provider는 `IDENTITY_VERIFICATION_MOCK_FORCE_FAIL` 환경변수 또는 요청의 `forceResult` 필드로 강제 실패를 트리거할 수 있어(개발/테스트 전용) 정책 시나리오를 재현할 수 있습니다.

**모듈 간 결합**: 인증 실패 시 Identity Verification 모듈은 Submission 모듈을 직접 호출하지 않고 `@nestjs/event-emitter`로 `IdentityVerificationFailedEvent`를 발행합니다. Submission 모듈이 이를 구독(`IdentityVerificationFailedListener`)해 `WARNING`/`DISQUALIFICATION` 액션에 따라 응시 상태를 갱신합니다. Identity Verification → Submission 방향의 import는 없습니다(순환 의존 방지, 정책 변경 시 Submission 쪽만 수정하면 됨).

### Exam (시험 회차)

`tb_exam` 기반. 상태(`SCHEDULED`/`OPEN`/`CLOSED`)는 컬럼으로 저장하지 않고 `open_at`/`close_at`과 현재 시각을 비교해 매 요청마다 계산합니다(`domain/exam-status.util.ts`, 정원과 무관 — 정원 초과로 자동 마감하는 로직 없음).

- `POST /exams` — 회차 추가(`ADMIN` 전용). `closeAt`이 `openAt`보다 뒤가 아니면 409.
- `GET /exams`, `GET /exams/:id` — 회차 목록/상세 조회. **같은 라우트를 쓰되 응답 DTO가 role에 따라 달라집니다**: 관리자는 `capacity`(정원) 포함, 일반 사용자는 미포함. 다른 모듈들처럼 관리자/사용자용 라우트를 따로 만들지 않고, 컨트롤러 안에서 `role`을 보고 응답 객체를 다르게 구성하는 방식을 씁니다(`ExamController.toResponse`).

### Role / 권한

`Role` enum은 `USER`, `ADMIN` 두 가지입니다. 본인인증 감사 로그 조회(`GET /identity-verification/sessions/:submissionId/logs`)와 수동 실격 처리(`POST /submissions/:id/disqualify`)는 `ADMIN` 전용입니다.

## 알려진 이슈 (스키마-코드 불일치)

`supabase/migrations/0001_init.sql`이 `tb_exam`/`tb_question`/`tb_user`/`tb_exam_session`/`tb_answers`/`tb_score`/`tb_exam_results`/`tb_proctoring_events` 중심의 새 ERD로 교체되었습니다. `tb_user`(Auth/User)와 `tb_exam`(Exam)은 이 ERD에 맞춰 작성되어 있지만, `question`/`submission`/`scoring`/`identity-verification` 모듈의 Repository는 아직 예전 테이블명(`questions`, `submissions`, `scores`, `identity_verification_*`)을 그대로 참조합니다. 이 모듈들을 실제로 쓰려면 새 ERD(`tb_question`, `tb_exam_session` 등)에 맞춰 별도로 재작성이 필요합니다.

(예전 `test` 모듈 — 존재하지 않는 `tests` 테이블을 참조하던 죽은 코드 — 은 이번에 `exam` 모듈로 교체하며 삭제했습니다.)

## 알려진 트레이드오프

### 시간대(Timezone) — 저장은 UTC, 표시는 프론트에서 로컬 변환

해외에서 응시하는 외국인 응시자가 있을 수 있으므로, 서버/DB는 항상 UTC 기준으로 저장하고 특정 지역 시간으로 변환해서 저장하지 않습니다. 모든 시간 컬럼은 `TIMESTAMPTZ`이고(`0003_convert_timestamps_to_timestamptz.sql`), 백엔드도 `new Date().toISOString()` / Postgres `now()`로 항상 UTC 값을 다룹니다. 사용자에게 보여줄 시각(응시 시간, 로그 시각 등)은 프론트엔드가 응시자의 로컬 타임존으로 변환해서 표시해야 합니다 — 서버가 특정 국가/지역 시간에 맞춰 저장하는 방식은 쓰지 않습니다. 새 시간 컬럼을 추가할 때도 항상 `TIMESTAMPTZ`를 쓸 것.

### RLS(Row Level Security)는 켜져 있지만 정책은 없음 — 인가는 애플리케이션 계층 책임

모든 테이블에 `ENABLE ROW LEVEL SECURITY`는 적용했지만 별도 정책(policy)은 만들지 않았습니다. 정책이 없는 상태에서 RLS가 켜져 있으면 anon/authenticated 키로는 기본적으로 모든 접근이 차단되고, 백엔드가 쓰는 service-role 키만 우회해 접근할 수 있습니다 — 즉 실질적인 인가(authorization) 판단은 여전히 애플리케이션 계층(`JwtAuthGuard` + `RolesGuard`)에서만 이뤄집니다. **Guard나 Service 코드에 버그가 있을 경우, 정책 기반 RLS라는 세밀한 안전망 없이 곧바로 데이터가 노출될 수 있다는 리스크**를 감수하는 결정입니다. 향후 민감한 테이블(예: `identity_verification_*`, `tb_user`)에 한해 사용자-스코프 Supabase 클라이언트(anon key + 사용자 JWT)를 병행 사용하고 실제 RLS 정책을 보조 방어선으로 추가하는 것으로 확장할 수 있습니다.

### `@nestjs/event-emitter`는 인메모리 기반

Identity Verification → Submission 간 결합을 낮추기 위해 쓰는 `@nestjs/event-emitter`는 프로세스 인메모리 이벤트 버스입니다. 인스턴스를 여러 개로 스케일아웃하면 한 인스턴스가 발행한 이벤트를 다른 인스턴스의 리스너가 받지 못해 유실될 수 있습니다. 단일 인스턴스 운영을 전제로 한 선택이며, 다중 인스턴스로 전환할 때는 Redis pub/sub 등 외부 메시지 브로커로 교체가 필요합니다.
