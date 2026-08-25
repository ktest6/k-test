import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
} from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { AuthService } from '../../../auth/application/services/auth.service';
import { ExamSession } from '../../../exam-session/domain/entities/exam-session.entity';
import { ExamSessionService } from '../../../exam-session/application/services/exam-session.service';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
import { TestQuickStartService } from './test-quick-start.service';

function buildConfig(overrides: Partial<{ env: string }> = {}): ConfigType<typeof appConfig> {
  return { env: overrides.env ?? 'development' } as ConfigType<typeof appConfig>;
}

function buildUser(): User {
  return new User(
    '100',
    'test-quick-1@ktest.local',
    'TEST',
    'USER',
    'KOR',
    '2000-01-01',
    null,
    null,
    null,
    new Date(),
    new Date(),
    new Date(),
    0,
    null,
    new Date(),
    new Date(),
    null,
  );
}

function buildSession(): ExamSession {
  return new ExamSession(
    '200',
    '100',
    SessionStatus.INPROGRESS,
    0,
    new Date(),
    null,
    null,
    null,
    new Date(),
  );
}

function buildUserService(overrides: Partial<{ register: jest.Mock }> = {}) {
  return {
    register: jest.fn().mockResolvedValue(buildUser()),
    ...overrides,
  } as unknown as UserService;
}

function buildExamSessionService(overrides: Partial<{ start: jest.Mock }> = {}) {
  return {
    start: jest.fn().mockResolvedValue(buildSession()),
    ...overrides,
  } as unknown as ExamSessionService;
}

function buildAuthService(overrides: Partial<{ issueTestAccessToken: jest.Mock }> = {}) {
  return {
    issueTestAccessToken: jest.fn().mockReturnValue({
      accessToken: 'token',
      refreshToken: 'refresh',
      expiresIn: 3600,
      userId: '100',
      email: 'test-quick-1@ktest.local',
    }),
    ...overrides,
  } as unknown as AuthService;
}

function buildSupabaseService(
  errors: { identity?: { message: string }; earphone?: { message: string } } = {},
) {
  const insertMock = jest.fn().mockResolvedValue({ error: null });
  const identityInsert = jest.fn().mockResolvedValue({ error: errors.identity ?? null });
  const earphoneInsert = jest.fn().mockResolvedValue({ error: errors.earphone ?? null });
  const fromMock = jest.fn((table: string) => {
    if (table === 'tb_identity_logs') {
      return { insert: identityInsert };
    }
    if (table === 'tb_earphone_logs') {
      return { insert: earphoneInsert };
    }
    return { insert: insertMock };
  });
  const client = { from: fromMock };
  return {
    service: { getAdminClient: () => client } as unknown as SupabaseService,
    identityInsert,
    earphoneInsert,
  };
}

describe('TestQuickStartService.quickStart', () => {
  it('rejects in production', async () => {
    const service = new TestQuickStartService(
      buildUserService(),
      buildExamSessionService(),
      buildAuthService(),
      buildSupabaseService().service,
      buildConfig({ env: 'production' }),
    );

    await expect(service.quickStart()).rejects.toThrow(ForbiddenDomainException);
  });

  it('creates a test user, starts a session, seeds passing verification logs, and issues a token', async () => {
    const register = jest.fn().mockResolvedValue(buildUser());
    const start = jest.fn().mockResolvedValue(buildSession());
    const issueTestAccessToken = jest.fn().mockReturnValue({
      accessToken: 'token',
      refreshToken: 'refresh',
      expiresIn: 3600,
      userId: '100',
      email: 'test-quick-1@ktest.local',
    });
    const { service: supabaseService, identityInsert, earphoneInsert } = buildSupabaseService();

    const service = new TestQuickStartService(
      buildUserService({ register }),
      buildExamSessionService({ start }),
      buildAuthService({ issueTestAccessToken }),
      supabaseService,
      buildConfig(),
    );

    const result = await service.quickStart();

    expect(register).toHaveBeenCalled();
    expect(start).toHaveBeenCalledWith('100');
    expect(identityInsert).toHaveBeenCalledWith(
      expect.objectContaining({ exam_session_id: 200, matched: true }),
    );
    expect(earphoneInsert).toHaveBeenCalledWith(
      expect.objectContaining({ exam_session_id: 200, earphone_detected: false }),
    );
    expect(issueTestAccessToken).toHaveBeenCalledWith('100', 'test-quick-1@ktest.local');
    expect(result).toEqual({
      accessToken: 'token',
      userId: '100',
      email: 'test-quick-1@ktest.local',
      examSessionId: '200',
      status: SessionStatus.INPROGRESS,
      verified: true,
    });
  });

  it('throws when seeding the identity log fails', async () => {
    const { service: supabaseService } = buildSupabaseService({ identity: { message: 'db down' } });
    const service = new TestQuickStartService(
      buildUserService(),
      buildExamSessionService(),
      buildAuthService(),
      supabaseService,
      buildConfig(),
    );

    await expect(service.quickStart()).rejects.toThrow(ConflictDomainException);
  });

  it('throws when seeding the earphone log fails', async () => {
    const { service: supabaseService } = buildSupabaseService({ earphone: { message: 'db down' } });
    const service = new TestQuickStartService(
      buildUserService(),
      buildExamSessionService(),
      buildAuthService(),
      supabaseService,
      buildConfig(),
    );

    await expect(service.quickStart()).rejects.toThrow(ConflictDomainException);
  });
});
