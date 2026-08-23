import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  IdentityProviderPort,
  VerifyIdentityInput,
  VerifyIdentityResult,
} from '../../../ai/domain/ports/identity-provider.port';
import { ExamSessionAccessService } from '../../../exam-session/application/services/exam-session-access.service';
import { User } from '../../../user/domain/entities/user.entity';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';
import { UserService } from '../../../user/application/services/user.service';
import { VerifyIdCardDto } from '../dto/verify-id-card.dto';
import { IdCardVerificationService } from './id-card-verification.service';

function buildUser(
  idType: IdentityDocumentType | null = IdentityDocumentType.PASSPORT,
  idNumber: string | null = 'M12345678',
): User {
  return new User(
    '9',
    'user@test.local',
    'GILDONG',
    'HONG',
    'KR',
    '1995-03-21',
    idType,
    idNumber,
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

function buildDto(): VerifyIdCardDto {
  return {
    examSessionId: '7',
    capturedAt: '2026-08-04T13:05:00+09:00',
    idCardPath: '9/7/id-card.jpg',
    facePath: '9/7/face.jpg',
  };
}

function buildResult(overrides: Partial<VerifyIdentityResult> = {}): VerifyIdentityResult {
  return {
    verified: true,
    faceVerified: true,
    similarity: 92.4,
    threshold: 80,
    matchedFaceCount: 1,
    unmatchedFaceCount: 0,
    applicantVerified: true,
    documentType: 'passport',
    fieldMatches: { last_name: true },
    message: '본인인증 성공',
    raw: { verified: true },
    ...overrides,
  };
}

function buildClient(
  overrides: {
    download?: jest.Mock;
    insert?: jest.Mock;
    remove?: jest.Mock;
    maybeSingle?: jest.Mock;
  } = {},
) {
  const download =
    overrides.download ??
    jest.fn().mockResolvedValue({
      data: { arrayBuffer: () => Promise.resolve(Buffer.from('img')), type: 'image/jpeg' },
      error: null,
    });
  const insert = overrides.insert ?? jest.fn().mockResolvedValue({ data: null, error: null });
  const remove = overrides.remove ?? jest.fn().mockResolvedValue({ data: null, error: null });
  const maybeSingle = overrides.maybeSingle ?? jest.fn().mockResolvedValue({ data: null });

  const queryBuilder: {
    insert: jest.Mock;
    select: jest.Mock;
    eq: jest.Mock;
    order: jest.Mock;
    limit: jest.Mock;
    maybeSingle: jest.Mock;
  } = {
    insert,
    select: jest.fn(),
    eq: jest.fn(),
    order: jest.fn(),
    limit: jest.fn(),
    maybeSingle,
  };
  queryBuilder.select.mockReturnValue(queryBuilder);
  queryBuilder.eq.mockReturnValue(queryBuilder);
  queryBuilder.order.mockReturnValue(queryBuilder);
  queryBuilder.limit.mockReturnValue(queryBuilder);

  return {
    from: jest.fn().mockReturnValue(queryBuilder),
    storage: { from: jest.fn().mockReturnValue({ download, remove }) },
  };
}

function buildService(
  overrides: {
    examSessionAccessService?: Partial<ExamSessionAccessService>;
    userService?: Partial<UserService>;
    identityProvider?: Partial<IdentityProviderPort>;
    client?: {
      download?: jest.Mock;
      insert?: jest.Mock;
      remove?: jest.Mock;
      maybeSingle?: jest.Mock;
    };
  } = {},
) {
  const examSessionAccessService = {
    assertOwnedInProgress: jest.fn().mockResolvedValue(undefined),
    ...overrides.examSessionAccessService,
  } as unknown as ExamSessionAccessService;
  const userService = {
    findById: jest.fn().mockResolvedValue(buildUser()),
    ...overrides.userService,
  } as unknown as UserService;
  const identityProvider = {
    verify: jest
      .fn<Promise<VerifyIdentityResult>, [VerifyIdentityInput]>()
      .mockResolvedValue(buildResult()),
    ...overrides.identityProvider,
  };
  const client = buildClient(overrides.client);
  const supabaseService = {
    getAdminClient: jest.fn().mockReturnValue(client),
  } as unknown as SupabaseService;

  return {
    service: new IdCardVerificationService(
      supabaseService,
      examSessionAccessService,
      userService,
      identityProvider,
    ),
    client,
    examSessionAccessService,
    userService,
    identityProvider,
  };
}

describe('IdCardVerificationService.verify', () => {
  it('rejects paths outside the caller-owned folder before checking anything else', async () => {
    const assertOwnedInProgress = jest.fn().mockResolvedValue(undefined);
    const { service } = buildService({ examSessionAccessService: { assertOwnedInProgress } });

    await expect(
      service.verify('9', { ...buildDto(), idCardPath: '999/7/id-card.jpg' }),
    ).rejects.toThrow(ForbiddenDomainException);
    expect(assertOwnedInProgress).not.toHaveBeenCalled();
  });

  it("calls the identity provider with the user's passport number and stores the result", async () => {
    const identityProvider = {
      verify: jest
        .fn<Promise<VerifyIdentityResult>, [VerifyIdentityInput]>()
        .mockResolvedValue(buildResult()),
    };
    const insert = jest.fn().mockResolvedValue({ data: null, error: null });
    const assertOwnedInProgress = jest.fn().mockResolvedValue(undefined);
    const { service } = buildService({
      identityProvider,
      client: { insert },
      examSessionAccessService: { assertOwnedInProgress },
    });

    const result = await service.verify('9', buildDto());

    expect(assertOwnedInProgress).toHaveBeenCalledWith('7', '9');
    expect(identityProvider.verify).toHaveBeenCalledWith(
      expect.objectContaining({
        examId: '7',
        examineeId: '9',
        firstName: 'GILDONG',
        lastName: 'HONG',
        birthDate: '1995-03-21',
        documentNumber: 'M12345678',
      }),
    );
    expect(insert).toHaveBeenCalledWith(
      expect.objectContaining({
        exam_session_id: 7,
        matched: true,
        confidence: 0.924,
        document_type: 'passport',
        raw_response: { verified: true },
      }),
    );
    expect(result).toEqual({
      matched: true,
      confidence: 0.924,
      faceVerified: true,
      similarity: 92.4,
      threshold: 80,
      matchedFaceCount: 1,
      unmatchedFaceCount: 0,
      applicantVerified: true,
      documentType: 'passport',
      fieldMatches: { last_name: true },
      message: '본인인증 성공',
    });
  });

  it('deletes only the id card image when the match succeeds — the face image is reused by monitoring', async () => {
    const identityProvider = {
      verify: jest
        .fn<Promise<VerifyIdentityResult>, [VerifyIdentityInput]>()
        .mockResolvedValue(buildResult({ verified: true })),
    };
    const remove = jest.fn().mockResolvedValue({ data: null, error: null });
    const { service } = buildService({ identityProvider, client: { remove } });

    await service.verify('9', buildDto());

    expect(remove).toHaveBeenCalledWith(['9/7/id-card.jpg']);
    expect(remove).not.toHaveBeenCalledWith(expect.arrayContaining(['9/7/face.jpg']));
  });

  it('deletes both images when the match fails — a mismatched face is never reused', async () => {
    const identityProvider = {
      verify: jest
        .fn<Promise<VerifyIdentityResult>, [VerifyIdentityInput]>()
        .mockResolvedValue(buildResult({ verified: false })),
    };
    const remove = jest.fn().mockResolvedValue({ data: null, error: null });
    const { service } = buildService({ identityProvider, client: { remove } });

    await service.verify('9', buildDto());

    expect(remove).toHaveBeenCalledWith(['9/7/id-card.jpg', '9/7/face.jpg']);
  });

  it('does not attempt to delete the id card image when the provider call fails', async () => {
    const identityProvider = {
      verify: jest.fn().mockRejectedValue(new Error('fastapi unreachable')),
    };
    const remove = jest.fn();
    const { service } = buildService({ identityProvider, client: { remove } });

    await expect(service.verify('9', buildDto())).rejects.toThrow(ConflictDomainException);
    expect(remove).not.toHaveBeenCalled();
  });

  it('does not fail verification when deleting the id card image fails', async () => {
    const remove = jest.fn().mockResolvedValue({ data: null, error: { message: 'boom' } });
    const { service } = buildService({ client: { remove } });

    await expect(service.verify('9', buildDto())).resolves.toMatchObject({ matched: true });
  });

  it('does not treat a provider failure as a pass — throws instead of defaulting to matched', async () => {
    const identityProvider = {
      verify: jest.fn().mockRejectedValue(new Error('fastapi unreachable')),
    };
    const insert = jest.fn();
    const { service } = buildService({ identityProvider, client: { insert } });

    await expect(service.verify('9', buildDto())).rejects.toThrow(ConflictDomainException);
    expect(insert).not.toHaveBeenCalled();
  });

  it('throws when an image cannot be downloaded from storage', async () => {
    const download = jest.fn().mockResolvedValue({ data: null, error: { message: 'not found' } });
    const { service } = buildService({ client: { download } });

    await expect(service.verify('9', buildDto())).rejects.toThrow(NotFoundDomainException);
  });

  it('rejects when the caller never registered a passport number', async () => {
    const userService = { findById: jest.fn().mockResolvedValue(buildUser(null, null)) };
    const identityProvider = { verify: jest.fn() };
    const { service } = buildService({ userService, identityProvider });

    await expect(service.verify('9', buildDto())).rejects.toThrow(ConflictDomainException);
    expect(identityProvider.verify).not.toHaveBeenCalled();
  });
});

describe('IdCardVerificationService.cleanupVerifiedFaceImage', () => {
  it('deletes the verified face image when one exists', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: { face_path: '9/7/face.jpg' } });
    const remove = jest.fn().mockResolvedValue({ data: null, error: null });
    const { service } = buildService({ client: { maybeSingle, remove } });

    await service.cleanupVerifiedFaceImage('7');

    expect(remove).toHaveBeenCalledWith(['9/7/face.jpg']);
  });

  it('does nothing when there is no verified face image on record', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: null });
    const remove = jest.fn();
    const { service } = buildService({ client: { maybeSingle, remove } });

    await service.cleanupVerifiedFaceImage('7');

    expect(remove).not.toHaveBeenCalled();
  });

  it('does not throw when deleting the face image fails', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: { face_path: '9/7/face.jpg' } });
    const remove = jest.fn().mockResolvedValue({ data: null, error: { message: 'boom' } });
    const { service } = buildService({ client: { maybeSingle, remove } });

    await expect(service.cleanupVerifiedFaceImage('7')).resolves.toBeUndefined();
  });
});

describe('IdCardVerificationService.hasVerifiedSession', () => {
  it('returns true when a matched log exists for this session', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: { id: 'log-1' } });
    const { service } = buildService({ client: { maybeSingle } });

    await expect(service.hasVerifiedSession('7')).resolves.toBe(true);
  });

  it('returns false when no matched log exists', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: null });
    const { service } = buildService({ client: { maybeSingle } });

    await expect(service.hasVerifiedSession('7')).resolves.toBe(false);
  });
});
