import { registerAs } from '@nestjs/config';

export interface AppConfig {
  env: string;
  port: number;
  corsOrigin: string;
  swaggerEnabled: boolean;
  /**
   * 시험 시작 시 본인인증(matched:true 기록) 완료를 요구할지 여부. AI팀의 본인인증
   * 서비스가 아직 배포되지 않은 개발/테스트 기간에만 false로 내려 임시로 우회한다.
   * 기본값은 true(강제)라 값을 명시적으로 안 내리면 항상 안전한 쪽으로 동작한다 —
   * 실제 서비스 배포 전에는 반드시 다시 true로(또는 env var 자체를 제거) 되돌릴 것.
   */
  requireIdentityVerification: boolean;
  /**
   * 시험 시작 시 이어폰 미착용 확인(earphone_detected:false 기록) 완료를 요구할지 여부.
   * requireIdentityVerification과 같은 이유(AI팀 서비스 미배포 기간)로 임시 우회용.
   * 기본값은 true(강제) — 실제 서비스 배포 전에는 반드시 다시 true로 되돌릴 것.
   */
  requireEarphoneCheck: boolean;
  /**
   * 시선 캘리브레이션(calibrate) 통신 실패를 에러로 알릴지 여부. 기본값 true(강제)일 때
   * 실패하면 409 에러를 던진다. AI팀 모니터링 서비스가 아직 배포되지 않은 개발/테스트
   * 기간에는 false로 내려 실패해도 조용히 "캘리브레이션 안 됨"으로 처리할 수 있다.
   * analyze(웹캠 프레임 분석)는 이 플래그와 무관하게 항상 실패를 조용히 처리한다 —
   * 시험 진행 중 계속 호출되는 API라 실패할 때마다 에러를 던지면 응시 화면이 깨지기
   * 때문에 이건 배포 여부와 상관없는 영구적인 설계 원칙이다.
   */
  requireMonitoringService: boolean;
  /**
   * 미완료 최종 리포트(/finalize) 재시도 스케줄러(5분 주기) 동작 여부. assessment
   * 서비스가 로컬에 항상 떠 있는 게 아닌 개발 환경에서는 매 5분마다 실패 로그만
   * 반복해서 쌓이는 걸 막기 위해 false로 꺼둘 수 있다. 기본값 true(운영 기준 항상 켜짐).
   */
  reportRetrySchedulerEnabled: boolean;
  supabase: {
    url: string;
    anonKey: string;
    serviceRoleKey: string;
  };
  identityVerification: {
    minIntervalMinutes: number;
    maxIntervalMinutes: number;
    maxFailuresBeforeDisqualification: number;
    mockForceFail: boolean;
  };
  jwt: {
    accessSecret: string;
    accessExpiresIn: string;
    refreshSecret: string;
    refreshExpiresIn: string;
  };
  admin: {
    /** 관리자 계정 생성 시 요구하는 공유 비밀값 — 첫 관리자 부트스트랩용. */
    signupSecret: string;
  };
  monitoring: {
    /** 신분증-얼굴 대조/이어폰 감지/부정행위 감지(웹캠 프레임 분석)를 맡는 서비스 베이스 URL — 세 기능 모두 같은 서비스라 하나로 공유한다. */
    url: string;
  };
  assessment: {
    /** 답안 채점(writing/speaking)을 맡는 assessment 서비스 베이스 URL. */
    url: string;
    /** 설정돼 있으면 X-API-Key 헤더로 실어 보낸다. 비어있으면 헤더 자체를 안 보냄(assessment 서비스 개발 모드). */
    apiKey: string;
  };
  mail: {
    smtpHost: string;
    smtpPort: number;
    smtpUser: string;
    smtpPassword: string;
    /** 발신자 표시 (예: "K-TEST <no-reply@ktest.local>"). */
    from: string;
  };
}

export const appConfig = registerAs('app', (): AppConfig => ({
  env: process.env.NODE_ENV ?? 'development',
  port: parseInt(process.env.PORT ?? '3000', 10),
  corsOrigin: process.env.CORS_ORIGIN ?? '*',
  swaggerEnabled: (process.env.SWAGGER_ENABLED ?? 'true') === 'true',
  requireIdentityVerification: (process.env.REQUIRE_IDENTITY_VERIFICATION ?? 'true') === 'true',
  requireEarphoneCheck: (process.env.REQUIRE_EARPHONE_CHECK ?? 'true') === 'true',
  requireMonitoringService: (process.env.REQUIRE_MONITORING_SERVICE ?? 'true') === 'true',
  reportRetrySchedulerEnabled: (process.env.ENABLE_REPORT_RETRY_SCHEDULER ?? 'true') === 'true',
  supabase: {
    url: process.env.SUPABASE_URL ?? '',
    anonKey: process.env.SUPABASE_ANON_KEY ?? '',
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY ?? '',
  },
  identityVerification: {
    minIntervalMinutes: parseInt(process.env.IDENTITY_VERIFICATION_MIN_INTERVAL_MINUTES ?? '5', 10),
    maxIntervalMinutes: parseInt(
      process.env.IDENTITY_VERIFICATION_MAX_INTERVAL_MINUTES ?? '15',
      10,
    ),
    maxFailuresBeforeDisqualification: parseInt(
      process.env.IDENTITY_VERIFICATION_MAX_FAILURES_BEFORE_DISQUALIFICATION ?? '2',
      10,
    ),
    mockForceFail: (process.env.IDENTITY_VERIFICATION_MOCK_FORCE_FAIL ?? 'false') === 'true',
  },
  jwt: {
    accessSecret: process.env.JWT_ACCESS_SECRET ?? '',
    accessExpiresIn: process.env.JWT_ACCESS_EXPIRES_IN ?? '1h',
    refreshSecret: process.env.JWT_REFRESH_SECRET ?? '',
    refreshExpiresIn: process.env.JWT_REFRESH_EXPIRES_IN ?? '14d',
  },
  admin: {
    signupSecret: process.env.ADMIN_SIGNUP_SECRET ?? '',
  },
  monitoring: {
    url: process.env.MONITORING_URL ?? '',
  },
  assessment: {
    url: process.env.ASSESSMENT_URL ?? '',
    apiKey: process.env.ASSESSMENT_API_KEY ?? '',
  },
  mail: {
    smtpHost: process.env.SMTP_HOST ?? '',
    smtpPort: parseInt(process.env.SMTP_PORT ?? '587', 10),
    smtpUser: process.env.SMTP_USER ?? '',
    smtpPassword: process.env.SMTP_PASSWORD ?? '',
    from: process.env.SMTP_FROM ?? 'K-TEST <no-reply@ktest.local>',
  },
}));
