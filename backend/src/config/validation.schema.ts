import * as Joi from 'joi';

export const validationSchema = Joi.object({
  NODE_ENV: Joi.string().valid('development', 'production', 'test').default('development'),
  PORT: Joi.number().default(3000),
  CORS_ORIGIN: Joi.string().default('*'),
  SWAGGER_ENABLED: Joi.string().valid('true', 'false').default('true'),

  SUPABASE_URL: Joi.string().uri().required(),
  SUPABASE_ANON_KEY: Joi.string().required(),
  SUPABASE_SERVICE_ROLE_KEY: Joi.string().required(),

  IDENTITY_VERIFICATION_MIN_INTERVAL_MINUTES: Joi.number().positive().default(5),
  IDENTITY_VERIFICATION_MAX_INTERVAL_MINUTES: Joi.number().positive().default(15),
  IDENTITY_VERIFICATION_MAX_FAILURES_BEFORE_DISQUALIFICATION: Joi.number()
    .integer()
    .min(0)
    .default(2),
  IDENTITY_VERIFICATION_MOCK_FORCE_FAIL: Joi.string().valid('true', 'false').default('false'),

  JWT_ACCESS_SECRET: Joi.string().min(16).required(),
  JWT_ACCESS_EXPIRES_IN: Joi.string().default('1h'),
  JWT_REFRESH_SECRET: Joi.string().min(16).required(),
  JWT_REFRESH_EXPIRES_IN: Joi.string().default('14d'),
});
