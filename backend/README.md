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

기동 후 `http://localhost:3000/docs`에서 Swagger UI로 전체 API(Auth/User/Exam/Verifications/Question/Submission/Scoring/AI, 8개 태그)를 확인할 수 있습니다.

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

기본 모듈: `auth`, `user`, `exam`, `verifications`, `question`, `submission`, `scoring`, `ai`.

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

### Verifications (본인인증)

`/verifications` 아래에 인증 타입별로 고정 경로를 둡니다 — 지금은 `id-card`(신분증-얼굴 대조) 하나만 구현되어 있고, 나중에 다른 타입(예: 이어폰 착용 여부 확인)을 추가할 때는 이 컨트롤러를 건드리지 않고 형제 컨트롤러(`@Controller('verifications/earphone')` 등)를 새로 만들면 됩니다.

**id-card (신분증-얼굴 대조)**:

- `POST /verifications/id-card/upload-url` — 프론트가 Storage에 직접 업로드할 수 있는 signed URL 발급. `fileType`(`ID_CARD` | `FACE`)별로 한 번씩, 총 두 번 호출해서 신분증 이미지와 웹캠 캡처 이미지 각각의 signed URL을 받습니다. 경로는 프론트가 아니라 **서버가** `${userId}/${sessionId}/...` 형태로 정하므로, 발급 단계부터 다른 사용자 경로로 업로드하는 게 원천 차단됩니다. 요청자가 그 `sessionId`(=`tb_exam_session.exam_session_id`)의 소유자인지도 여기서 확인합니다.
  - signed URL 발급 자체(`createSignedUploadUrl` 호출 + 에러 처리)는 `IdCardUploadUrlService`가 하지 않고 공용 `StorageUploadUrlService`(`src/infrastructure/supabase/storage-upload-url.service.ts`, 전역 모듈)에 위임합니다. `IdCardUploadUrlService`는 id-card만의 규칙(세션 소유권, 허용 content-type, 경로 이름 규칙)만 정하고 마지막에 `bucket`/`path`만 넘겨줍니다. 나중에 영상/음성 녹음처럼 다른 파일 업로드 기능이 생기면, 그 기능만의 규칙을 가진 서비스를 하나 더 만들고 이 공용 서비스를 그대로 재사용하면 됩니다 — signed URL 발급 로직 자체는 중복 구현할 필요 없음.
- `POST /verifications/id-card/verify` — 업로드된 신분증/웹캠 이미지 경로를 받아 (1) 경로가 본인 소유 폴더인지, (2) 세션 소유자인지 재검증한 뒤 `identity_logs`에 결과를 기록합니다. 얼굴 대조를 맡을 FastAPI 서비스가 아직 연동되지 않아 `matched`/`confidence`는 현재 항상 `null`로 반환됩니다 (연동 시점과 필요한 작업은 `id-card-verification.service.ts`의 TODO 주석 참고).
- 이미지는 대조 완료 직후 Storage에서 삭제하는 게 원칙이지만, 아직 실제 대조가 일어나지 않으므로(위 이유) 지금은 삭제를 보류해뒀습니다 — FastAPI 연동 후 대조 직후 시점으로 옮겨서 다시 활성화할 것.

**아직 안 만든 것 / 알려진 갭**: 본인인증 실패 시 응시 상태를 `WARNING`/`DISQUALIFICATION`으로 승격하는 로직(`VerificationFailureAction` enum, `VerificationFailedEvent`)은 Submission 모듈의 `verification-failed.listener.ts`에 리스너까지 준비되어 있지만, 지금은 아무도 이 이벤트를 발행하지 않습니다 (`id-card-verification.service.ts`가 항상 `matched: null`만 반환하기 때문). FastAPI 연동으로 실제 `matched: false` 케이스가 생기면, 연속 실패 횟수를 세서 이 이벤트를 발행하는 정책 로직을 다시 붙여야 합니다.

**모듈 간 결합**: 실패 이벤트는 `@nestjs/event-emitter`로 발행하고 Submission 모듈이 구독하는 구조를 그대로 유지합니다(`VERIFICATION_FAILED_EVENT`). Verifications → Submission 방향의 import는 없습니다(순환 의존 방지, 정책 변경 시 Submission 쪽만 수정하면 됨).

### Exam (시험 회차)

`tb_exam` 기반. 상태(`SCHEDULED`/`OPEN`/`CLOSED`)는 컬럼으로 저장하지 않고 `open_at`/`close_at`과 현재 시각을 비교해 매 요청마다 계산합니다(`domain/exam-status.util.ts`, 정원과 무관 — 정원 초과로 자동 마감하는 로직 없음).

- `POST /exams` — 회차 추가(`ADMIN` 전용). `closeAt`이 `openAt`보다 뒤가 아니면 409. **`roundName`은 요청에 없습니다** — 서버가 `"{연도}{그 해 순차번호}"`(예: `202601`, `202602`) 형식으로 자동 생성합니다(`ExamService.generateRoundName`). 관리자가 직접 입력하게 하면 오타로 표기가 흔들릴 수 있어서 아예 입력 필드를 없앴습니다. 순차번호는 그 해 가장 큰 번호 다음 값이고, soft-delete된 회차도 번호를 재사용하지 않으며, `tb_exam.round_name`에 UNIQUE 제약을 걸어 동시 생성 시 번호가 겹치면 409로 거부합니다(재시도하면 해결됨).
- `GET /exams`, `GET /exams/:id` — 회차 목록/상세 조회. **같은 라우트를 쓰되 응답 DTO가 role에 따라 달라집니다**: 관리자는 `capacity`(정원) 포함, 일반 사용자는 미포함. 다른 모듈들처럼 관리자/사용자용 라우트를 따로 만들지 않고, 컨트롤러 안에서 `role`을 보고 응답 객체를 다르게 구성하는 방식을 씁니다(`ExamController.toResponse`).

### Role / 권한

`Role` enum은 `USER`, `ADMIN` 두 가지입니다. 수동 실격 처리(`POST /submissions/:id/disqualify`)는 `ADMIN` 전용입니다.

## 알려진 이슈 (스키마-코드 불일치)

`supabase/migrations/0001_init.sql`이 `tb_exam`/`tb_question`/`tb_user`/`tb_exam_session`/`tb_answers`/`tb_score`/`tb_exam_results`/`tb_proctoring_events` 중심의 새 ERD로 교체되었습니다. `tb_user`(Auth/User), `tb_exam`(Exam), `verifications`(id-card)는 이 ERD에 맞춰 작성되어 있지만, `question`/`submission`/`scoring` 모듈의 Repository는 아직 예전 테이블명(`questions`, `submissions`, `scores`)을 그대로 참조합니다. 이 모듈들을 실제로 쓰려면 새 ERD(`tb_question`, `tb_exam_session` 등)에 맞춰 별도로 재작성이 필요합니다.

(예전 `test` 모듈 — 존재하지 않는 `tests` 테이블을 참조하던 죽은 코드 — 은 `exam` 모듈로 교체하며 삭제했습니다. 예전 `identity-verification` 모듈 — 세션/시도/로그 3단계 저장 + Mock provider로 구성된 사전/주기 인증 mock 시스템 — 도 참조하던 테이블이 새 ERD에 아예 없어 항상 500이 나는 죽은 코드였고, 실제 구현인 `verifications/id-card`로 대체되면서 통째로 삭제했습니다.)

## 알려진 트레이드오프

### 시간대(Timezone) — 저장은 UTC, 표시는 프론트에서 로컬 변환

해외에서 응시하는 외국인 응시자가 있을 수 있으므로, 서버/DB는 항상 UTC 기준으로 저장하고 특정 지역 시간으로 변환해서 저장하지 않습니다. 모든 시간 컬럼은 `TIMESTAMPTZ`이고(`0003_convert_timestamps_to_timestamptz.sql`), 백엔드도 `new Date().toISOString()` / Postgres `now()`로 항상 UTC 값을 다룹니다. 사용자에게 보여줄 시각(응시 시간, 로그 시각 등)은 프론트엔드가 응시자의 로컬 타임존으로 변환해서 표시해야 합니다 — 서버가 특정 국가/지역 시간에 맞춰 저장하는 방식은 쓰지 않습니다. 새 시간 컬럼을 추가할 때도 항상 `TIMESTAMPTZ`를 쓸 것.

### RLS(Row Level Security)는 켜져 있지만 정책은 없음 — 인가는 애플리케이션 계층 책임

모든 테이블에 `ENABLE ROW LEVEL SECURITY`는 적용했지만 별도 정책(policy)은 만들지 않았습니다. 정책이 없는 상태에서 RLS가 켜져 있으면 anon/authenticated 키로는 기본적으로 모든 접근이 차단되고, 백엔드가 쓰는 service-role 키만 우회해 접근할 수 있습니다 — 즉 실질적인 인가(authorization) 판단은 여전히 애플리케이션 계층(`JwtAuthGuard` + `RolesGuard`)에서만 이뤄집니다. **Guard나 Service 코드에 버그가 있을 경우, 정책 기반 RLS라는 세밀한 안전망 없이 곧바로 데이터가 노출될 수 있다는 리스크**를 감수하는 결정입니다. 향후 민감한 테이블(예: `identity_verification_*`, `tb_user`)에 한해 사용자-스코프 Supabase 클라이언트(anon key + 사용자 JWT)를 병행 사용하고 실제 RLS 정책을 보조 방어선으로 추가하는 것으로 확장할 수 있습니다.

### `@nestjs/event-emitter`는 인메모리 기반

Verifications → Submission 간 결합을 낮추기 위해 쓰는 `@nestjs/event-emitter`는 프로세스 인메모리 이벤트 버스입니다. 인스턴스를 여러 개로 스케일아웃하면 한 인스턴스가 발행한 이벤트를 다른 인스턴스의 리스너가 받지 못해 유실될 수 있습니다. 단일 인스턴스 운영을 전제로 한 선택이며, 다중 인스턴스로 전환할 때는 Redis pub/sub 등 외부 메시지 브로커로 교체가 필요합니다.
