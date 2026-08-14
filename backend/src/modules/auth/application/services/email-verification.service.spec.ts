import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { UserService } from '../../../user/application/services/user.service';
import { EmailVerificationService } from './email-verification.service';

type QueryResult = { data?: unknown; error?: { message: string } | null };

interface QueryChain {
  select: jest.Mock<QueryChain, unknown[]>;
  eq: jest.Mock<QueryChain, unknown[]>;
  update: jest.Mock<QueryChain, unknown[]>;
  delete: jest.Mock<QueryChain, unknown[]>;
  upsert: jest.Mock<Promise<QueryResult>, unknown[]>;
  maybeSingle: jest.Mock<Promise<QueryResult>, unknown[]>;
  then: (resolve: (value: QueryResult) => unknown) => Promise<unknown>;
}

function buildClient(results: QueryResult[]) {
  let i = 0;
  const nextResult = (): QueryResult => results[i++] ?? { data: null, error: null };

  function makeChain(): QueryChain {
    const chain = {} as QueryChain;
    chain.select = jest.fn(() => chain);
    chain.eq = jest.fn(() => chain);
    chain.update = jest.fn(() => chain);
    chain.delete = jest.fn(() => chain);
    chain.upsert = jest.fn(() => Promise.resolve(nextResult()));
    chain.maybeSingle = jest.fn(() => Promise.resolve(nextResult()));
    chain.then = (resolve) => Promise.resolve(nextResult()).then(resolve);
    return chain;
  }

  return { from: jest.fn(() => makeChain()) };
}

function buildSupabaseService(results: QueryResult[]) {
  const client = buildClient(results);
  return {
    supabaseService: {
      getAdminClient: jest.fn().mockReturnValue(client),
    } as unknown as SupabaseService,
    client,
  };
}

function buildUserService(overrides: Partial<{ existsByEmail: jest.Mock }> = {}) {
  return {
    existsByEmail: jest.fn().mockResolvedValue(false),
    ...overrides,
  } as unknown as UserService;
}

describe('EmailVerificationService.sendCode', () => {
  it('rejects when the email already belongs to an account', async () => {
    const { supabaseService } = buildSupabaseService([]);
    const userService = buildUserService({ existsByEmail: jest.fn().mockResolvedValue(true) });
    const service = new EmailVerificationService(supabaseService, userService);

    await expect(service.sendCode('taken@example.com')).rejects.toThrow(ConflictDomainException);
  });

  it('generates and stores a 6-digit code for a fresh email', async () => {
    const { supabaseService, client } = buildSupabaseService([{ data: null, error: null }]);
    const userService = buildUserService();
    const service = new EmailVerificationService(supabaseService, userService);

    const code = await service.sendCode('new@example.com');

    expect(code).toMatch(/^\d{6}$/);
    expect(client.from).toHaveBeenCalledWith('tb_email_verification');
  });

  it('throws when the upsert fails', async () => {
    const { supabaseService } = buildSupabaseService([{ data: null, error: { message: 'boom' } }]);
    const userService = buildUserService();
    const service = new EmailVerificationService(supabaseService, userService);

    await expect(service.sendCode('new@example.com')).rejects.toThrow(ConflictDomainException);
  });
});

describe('EmailVerificationService.verifyCode', () => {
  it('rejects when there is no pending verification for the email', async () => {
    const { supabaseService } = buildSupabaseService([{ data: null, error: null }]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.verifyCode('nobody@example.com', '123456')).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('rejects when the email was already verified', async () => {
    const { supabaseService } = buildSupabaseService([
      {
        data: {
          email: 'a@example.com',
          code: '123456',
          code_expires_at: new Date(Date.now() + 60_000).toISOString(),
          attempts: 0,
          verified_at: new Date().toISOString(),
        },
      },
    ]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.verifyCode('a@example.com', '123456')).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('rejects an expired code', async () => {
    const { supabaseService } = buildSupabaseService([
      {
        data: {
          email: 'a@example.com',
          code: '123456',
          code_expires_at: new Date(Date.now() - 1000).toISOString(),
          attempts: 0,
          verified_at: null,
        },
      },
    ]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.verifyCode('a@example.com', '123456')).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('rejects once the max attempt count is reached', async () => {
    const { supabaseService } = buildSupabaseService([
      {
        data: {
          email: 'a@example.com',
          code: '123456',
          code_expires_at: new Date(Date.now() + 60_000).toISOString(),
          attempts: 5,
          verified_at: null,
        },
      },
    ]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.verifyCode('a@example.com', '123456')).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('increments attempts and rejects on a wrong code', async () => {
    const { supabaseService, client } = buildSupabaseService([
      {
        data: {
          email: 'a@example.com',
          code: '123456',
          code_expires_at: new Date(Date.now() + 60_000).toISOString(),
          attempts: 1,
          verified_at: null,
        },
      },
      { data: null, error: null },
    ]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.verifyCode('a@example.com', '000000')).rejects.toThrow(
      ConflictDomainException,
    );
    expect(client.from).toHaveBeenCalledTimes(2);
  });

  it('marks the email verified when the code matches', async () => {
    const { supabaseService } = buildSupabaseService([
      {
        data: {
          email: 'a@example.com',
          code: '123456',
          code_expires_at: new Date(Date.now() + 60_000).toISOString(),
          attempts: 0,
          verified_at: null,
        },
      },
      { data: null, error: null },
    ]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.verifyCode('a@example.com', '123456')).resolves.toBeUndefined();
  });
});

describe('EmailVerificationService.consumeVerification', () => {
  it('rejects when the email was never verified', async () => {
    const { supabaseService } = buildSupabaseService([{ data: { verified_at: null } }]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.consumeVerification('a@example.com')).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('rejects when there is no pending record at all', async () => {
    const { supabaseService } = buildSupabaseService([{ data: null, error: null }]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    await expect(service.consumeVerification('nobody@example.com')).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('returns the verified timestamp and deletes the pending row', async () => {
    const verifiedAt = '2026-01-01T00:00:00.000Z';
    const { supabaseService, client } = buildSupabaseService([
      { data: { verified_at: verifiedAt } },
      { data: null, error: null },
    ]);
    const service = new EmailVerificationService(supabaseService, buildUserService());

    const result = await service.consumeVerification('a@example.com');

    expect(result).toEqual(new Date(verifiedAt));
    expect(client.from).toHaveBeenCalledTimes(2);
  });
});
