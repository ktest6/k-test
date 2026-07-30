process.env.SUPABASE_URL ??= 'https://example.supabase.co';
process.env.SUPABASE_ANON_KEY ??= 'test-anon-key';
process.env.SUPABASE_SERVICE_ROLE_KEY ??= 'test-service-role-key';
process.env.JWT_ACCESS_SECRET ??= 'test-access-secret-min-16-chars';
process.env.JWT_REFRESH_SECRET ??= 'test-refresh-secret-min-16-chars';

import { INestApplication } from '@nestjs/common';
import { Test, TestingModule } from '@nestjs/testing';
import request from 'supertest';
import { AppModule } from '../src/app.module';

describe('AppModule (e2e)', () => {
  let app: INestApplication;

  beforeAll(async () => {
    const moduleFixture: TestingModule = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close();
  });

  it('/health (GET) is publicly reachable and wraps the payload in the standard envelope', () => {
    return request(app.getHttpServer())
      .get('/health')
      .expect(200)
      .expect((res) => {
        const body = res.body as {
          success: boolean;
          statusCode: number;
          message: string;
          data: { status: string };
        };
        expect(body.success).toBe(true);
        expect(body.statusCode).toBe(200);
        expect(body.message).toBe('헬스체크 성공');
        expect(body.data.status).toBe('ok');
      });
  });

  it('/users/me (GET) rejects unauthenticated requests with the standard error envelope', () => {
    return request(app.getHttpServer())
      .get('/users/me')
      .expect(401)
      .expect((res) => {
        const body = res.body as { success: boolean; statusCode: number; data: unknown };
        expect(body.success).toBe(false);
        expect(body.statusCode).toBe(401);
        expect(body.data).toBeNull();
      });
  });
});
