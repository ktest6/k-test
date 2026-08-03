import { registerAs } from '@nestjs/config';

export interface AppConfig {
  env: string;
  port: number;
  corsOrigin: string;
  swaggerEnabled: boolean;
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
  fastApi: {
    /** 신분증-얼굴 대조를 맡는 FastAPI 서비스 베이스 URL. */
    url: string;
  };
  assessment: {
    /** 답안 채점(writing/speaking)을 맡는 assessment 서비스 베이스 URL. */
    url: string;
    /** 설정돼 있으면 X-API-Key 헤더로 실어 보낸다. 비어있으면 헤더 자체를 안 보냄(assessment 서비스 개발 모드). */
    apiKey: string;
  };
  monitoring: {
    /** 부정행위 감지(웹캠 프레임 분석)를 맡는 모니터링 서비스 베이스 URL. */
    url: string;
  };
}

export const appConfig = registerAs('app', (): AppConfig => ({
  env: process.env.NODE_ENV ?? 'development',
  port: parseInt(process.env.PORT ?? '3000', 10),
  corsOrigin: process.env.CORS_ORIGIN ?? '*',
  swaggerEnabled: (process.env.SWAGGER_ENABLED ?? 'true') === 'true',
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
  fastApi: {
    url: process.env.FASTAPI_URL ?? '',
  },
  assessment: {
    url: process.env.ASSESSMENT_URL ?? '',
    apiKey: process.env.ASSESSMENT_API_KEY ?? '',
  },
  monitoring: {
    url: process.env.MONITORING_URL ?? '',
  },
}));
