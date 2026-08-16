import * as bcrypt from 'bcrypt';
import {
  ConflictDomainException,
  UnauthorizedDomainException,
} from '../../../../common/exceptions/domain.exception';
import { User } from '../../domain/entities/user.entity';
import { IdentityDocumentType } from '../../domain/enums/identity-document-type.enum';
import { UserRepository } from '../../domain/user.repository.interface';
import { RegisterUserRequest, UserService } from './user.service';

jest.mock('bcrypt', () => ({ compare: jest.fn(), hash: jest.fn() }));
const mockedCompare = bcrypt.compare as unknown as jest.Mock;
const mockedHash = bcrypt.hash as unknown as jest.Mock;

function buildUser(): User {
  return new User(
    '9',
    'user@test.local',
    'GILDONG',
    'HONG',
    'KR',
    '1995-03-21',
    IdentityDocumentType.PASSPORT,
    'M12345678',
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

function buildRegisterRequest(overrides: Partial<RegisterUserRequest> = {}): RegisterUserRequest {
  return {
    email: 'user@test.local',
    password: '12341234!!',
    firstName: 'GILDONG',
    lastName: 'HONG',
    nationality: 'KOR',
    birthDate: '1995-03-21',
    termsAgreedAt: new Date(),
    privacyAgreedAt: new Date(),
    passportProcessingAgreedAt: new Date(),
    emailVerifiedAt: new Date(),
    voiceDataAiTrainingAgreedAt: null,
    ...overrides,
  };
}

function buildRepository(overrides: Partial<UserRepository> = {}) {
  return {
    existsByEmail: jest.fn().mockResolvedValue(false),
    existsByIdentityDocument: jest.fn().mockResolvedValue(false),
    register: jest.fn().mockResolvedValue(buildUser()),
    findById: jest.fn().mockResolvedValue(buildUser()),
    findByEmail: jest.fn().mockResolvedValue(buildUser()),
    findCredentialsByEmail: jest.fn(),
    recordLoginSuccess: jest.fn().mockResolvedValue(undefined),
    recordLoginFailure: jest.fn().mockResolvedValue(undefined),
    update: jest.fn(),
    list: jest.fn(),
    ...overrides,
  };
}

describe('UserService.register', () => {
  it('rejects when the email is already taken', async () => {
    const repository = buildRepository({ existsByEmail: jest.fn().mockResolvedValue(true) });
    const service = new UserService(repository);

    await expect(service.register(buildRegisterRequest())).rejects.toThrow(ConflictDomainException);
  });

  it('rejects when idType/idNumber are given and already registered to another account', async () => {
    const repository = buildRepository({
      existsByIdentityDocument: jest.fn().mockResolvedValue(true),
    });
    const service = new UserService(repository);

    await expect(
      service.register(
        buildRegisterRequest({ idType: IdentityDocumentType.PASSPORT, idNumber: 'M1' }),
      ),
    ).rejects.toThrow(ConflictDomainException);
  });

  it('does not check identity-document uniqueness when idType/idNumber are omitted', async () => {
    const existsByIdentityDocument = jest.fn();
    const repository = buildRepository({ existsByIdentityDocument });
    const service = new UserService(repository);

    await service.register(buildRegisterRequest());

    expect(existsByIdentityDocument).not.toHaveBeenCalled();
  });

  it('registers with the pre-verified email timestamp passed straight through', async () => {
    mockedHash.mockResolvedValueOnce('hashed');
    const register = jest.fn().mockResolvedValue(buildUser());
    const repository = buildRepository({ register });
    const service = new UserService(repository);
    const verifiedAt = new Date('2026-01-01T00:00:00.000Z');

    await service.register(buildRegisterRequest({ emailVerifiedAt: verifiedAt }));

    expect(register).toHaveBeenCalledWith(
      expect.objectContaining({ emailVerifiedAt: verifiedAt, passwordHash: 'hashed' }),
    );
  });

  it('passes voiceDataAiTrainingAgreedAt straight through, including when null (not agreed)', async () => {
    const register = jest.fn().mockResolvedValue(buildUser());
    const repository = buildRepository({ register });
    const service = new UserService(repository);
    const voiceDataAiTrainingAgreedAt = new Date('2026-01-01T00:00:00.000Z');

    await service.register(buildRegisterRequest({ voiceDataAiTrainingAgreedAt }));
    await service.register(buildRegisterRequest({ voiceDataAiTrainingAgreedAt: null }));

    expect(register).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ voiceDataAiTrainingAgreedAt }),
    );
    expect(register).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ voiceDataAiTrainingAgreedAt: null }),
    );
  });
});

describe('UserService.verifyCredentials', () => {
  it('logs in successfully when the password matches', async () => {
    const credentials = { user: buildUser(), passwordHash: 'hash' };
    mockedCompare.mockResolvedValueOnce(true);
    const repository = buildRepository({
      findCredentialsByEmail: jest.fn().mockResolvedValue(credentials),
    });
    const service = new UserService(repository);

    const result = await service.verifyCredentials('user@test.local', 'pw');

    expect(result).toBe(credentials.user);
    expect(repository.recordLoginSuccess).toHaveBeenCalledWith('9');
  });

  it('rejects with a generic message when the account does not exist', async () => {
    const repository = buildRepository({
      findCredentialsByEmail: jest.fn().mockResolvedValue(null),
    });
    const service = new UserService(repository);

    await expect(service.verifyCredentials('nobody@test.local', 'pw')).rejects.toThrow(
      UnauthorizedDomainException,
    );
  });

  it('rejects with the generic message when the password is wrong', async () => {
    const credentials = { user: buildUser(), passwordHash: 'hash' };
    mockedCompare.mockResolvedValueOnce(false);
    const repository = buildRepository({
      findCredentialsByEmail: jest.fn().mockResolvedValue(credentials),
    });
    const service = new UserService(repository);

    await expect(service.verifyCredentials('user@test.local', 'wrong')).rejects.toThrow(
      UnauthorizedDomainException,
    );
    expect(repository.recordLoginFailure).toHaveBeenCalledWith('9');
  });
});
