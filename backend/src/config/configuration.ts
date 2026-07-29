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
}));
