import { JwtService } from '@nestjs/jwt';
import {
  ConflictDomainException,
  UnauthorizedDomainException,
} from '../../../../common/exceptions/domain.exception';
import { Role } from '../../../../common/enums/role.enum';
import { AppConfig } from '../../../../config/configuration';
import { MailService } from '../../../../infrastructure/mail/mail.service';
import { Admin } from '../../../admin/domain/entities/admin.entity';
import { AdminService } from '../../../admin/application/services/admin.service';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
import { AdminSignUpDto } from '../dto/admin-sign-up.dto';
import { SignInDto } from '../dto/sign-in.dto';
import { SignUpDto } from '../dto/sign-up.dto';
import { AuthService } from './auth.service';
import { EmailVerificationService } from './email-verification.service';

function buildUser(): User {
  return new User(
    '9',
    'student@example.com',
    'GILDONG',
    'HONG',
    'KR',
    '1995-03-21',
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

function buildMailService() {
  return { sendVerificationCode: jest.fn().mockResolvedValue(undefined) } as unknown as MailService;
}

function buildEmailVerificationService(
  overrides: Partial<{
    sendCode: jest.Mock;
    verifyCode: jest.Mock;
    consumeVerification: jest.Mock;
  }> = {},
) {
  return {
    sendCode: jest.fn().mockResolvedValue('123456'),
    verifyCode: jest.fn().mockResolvedValue(undefined),
    consumeVerification: jest.fn().mockResolvedValue(new Date('2026-01-01T00:00:00.000Z')),
    ...overrides,
  } as unknown as EmailVerificationService;
}

function buildConfig(signupSecret: string): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
    requireIdentityVerification: true,
    requireEarphoneCheck: true,
    supabase: { url: '', anonKey: '', serviceRoleKey: '' },
    identityVerification: {
      minIntervalMinutes: 5,
      maxIntervalMinutes: 15,
      maxFailuresBeforeDisqualification: 2,
      mockForceFail: false,
    },
    jwt: {
      accessSecret: 'test-access-secret',
      accessExpiresIn: '1h',
      refreshSecret: 'test-refresh-secret',
      refreshExpiresIn: '14d',
    },
    admin: { signupSecret },
    assessment: { url: '', apiKey: '' },
    monitoring: { url: '' },
    mail: { smtpHost: '', smtpPort: 587, smtpUser: '', smtpPassword: '', from: '' },
  };
}

function buildAdmin(): Admin {
  return new Admin('1', 'admin1@test.com', '관리자', 0, null, new Date());
}

function buildDto(overrides: Partial<AdminSignUpDto> = {}): AdminSignUpDto {
  return {
    email: 'admin1@test.com',
    password: '12341234!!',
    name: '관리자',
    adminSecret: 'correct-secret-value',
    ...overrides,
  };
}

function buildJwtService() {
  return {
    sign: jest.fn().mockReturnValue('signed-token'),
    decode: jest.fn().mockReturnValue({ iat: 0, exp: 3600 }),
  } as unknown as JwtService;
}

describe('AuthService.adminSignUp', () => {
  function buildService(signupSecret = 'correct-secret-value') {
    const register = jest.fn().mockResolvedValue(buildAdmin());
    const adminService = { register } as unknown as AdminService;
    const userService = {} as unknown as UserService;
    const jwtService = buildJwtService();

    const service = new AuthService(
      userService,
      adminService,
      jwtService,
      buildMailService(),
      buildEmailVerificationService(),
      buildConfig(signupSecret),
    );
    return { service, register };
  }

  it('rejects when the admin secret does not match', async () => {
    const { service, register } = buildService('correct-secret-value');

    await expect(service.adminSignUp(buildDto({ adminSecret: 'wrong-secret' }))).rejects.toThrow(
      UnauthorizedDomainException,
    );
    expect(register).not.toHaveBeenCalled();
  });

  it('rejects when the admin secret has a different length', async () => {
    const { service, register } = buildService('correct-secret-value');

    await expect(service.adminSignUp(buildDto({ adminSecret: 'short' }))).rejects.toThrow(
      UnauthorizedDomainException,
    );
    expect(register).not.toHaveBeenCalled();
  });

  it('creates the admin and issues tokens when the secret matches', async () => {
    const { service, register } = buildService('correct-secret-value');

    const result = await service.adminSignUp(buildDto());

    expect(register).toHaveBeenCalledWith({
      email: 'admin1@test.com',
      password: '12341234!!',
      name: '관리자',
    });
    expect(result.accessToken).toBe('signed-token');
    expect(result.role).toBe(Role.ADMIN);
  });
});

describe('AuthService.adminSignIn', () => {
  it('issues an ADMIN-role token on successful credential check', async () => {
    const verifyCredentials = jest.fn().mockResolvedValue(buildAdmin());
    const adminService = { verifyCredentials } as unknown as AdminService;
    const userService = {} as unknown as UserService;
    const jwtService = buildJwtService();
    const service = new AuthService(
      userService,
      adminService,
      jwtService,
      buildMailService(),
      buildEmailVerificationService(),
      buildConfig('secret'),
    );
    const dto: SignInDto = { email: 'admin1@test.com', password: '12341234!!' };

    const result = await service.adminSignIn(dto);

    expect(verifyCredentials).toHaveBeenCalledWith('admin1@test.com', '12341234!!');
    expect(result.role).toBe(Role.ADMIN);
    expect(result.userId).toBe('1');
  });

  it('propagates the UnauthorizedDomainException from AdminService on bad credentials', async () => {
    const verifyCredentials = jest.fn().mockRejectedValue(new UnauthorizedDomainException('bad'));
    const adminService = { verifyCredentials } as unknown as AdminService;
    const userService = {} as unknown as UserService;
    const jwtService = buildJwtService();
    const service = new AuthService(
      userService,
      adminService,
      jwtService,
      buildMailService(),
      buildEmailVerificationService(),
      buildConfig('secret'),
    );

    await expect(
      service.adminSignIn({ email: 'admin1@test.com', password: 'wrong' }),
    ).rejects.toThrow(UnauthorizedDomainException);
  });
});

describe('AuthService.sendVerificationCode', () => {
  it('generates a code and sends it by mail', async () => {
    const sendCode = jest.fn().mockResolvedValue('654321');
    const userService = {} as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const sendVerificationCode = jest.fn().mockResolvedValue(undefined);
    const mailService = { sendVerificationCode } as unknown as MailService;
    const service = new AuthService(
      userService,
      adminService,
      buildJwtService(),
      mailService,
      buildEmailVerificationService({ sendCode }),
      buildConfig('secret'),
    );

    await service.sendVerificationCode({ email: 'student@example.com' });

    expect(sendCode).toHaveBeenCalledWith('student@example.com');
    expect(sendVerificationCode).toHaveBeenCalledWith('student@example.com', '654321');
  });

  it('propagates a conflict when the email is already registered', async () => {
    const sendCode = jest.fn().mockRejectedValue(new ConflictDomainException('taken'));
    const userService = {} as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const service = new AuthService(
      userService,
      adminService,
      buildJwtService(),
      buildMailService(),
      buildEmailVerificationService({ sendCode }),
      buildConfig('secret'),
    );

    await expect(service.sendVerificationCode({ email: 'taken@example.com' })).rejects.toThrow(
      ConflictDomainException,
    );
  });

  it('surfaces a clear error when the mail itself fails to send, instead of reporting success', async () => {
    const sendCode = jest.fn().mockResolvedValue('654321');
    const userService = {} as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const sendVerificationCode = jest.fn().mockRejectedValue(new Error('SMTP auth failed'));
    const mailService = { sendVerificationCode } as unknown as MailService;
    const service = new AuthService(
      userService,
      adminService,
      buildJwtService(),
      mailService,
      buildEmailVerificationService({ sendCode }),
      buildConfig('secret'),
    );

    await expect(service.sendVerificationCode({ email: 'student@example.com' })).rejects.toThrow(
      ConflictDomainException,
    );
  });
});

describe('AuthService.verifyEmail', () => {
  it('delegates to EmailVerificationService and does not issue tokens', async () => {
    const verifyCode = jest.fn().mockResolvedValue(undefined);
    const userService = {} as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const service = new AuthService(
      userService,
      adminService,
      buildJwtService(),
      buildMailService(),
      buildEmailVerificationService({ verifyCode }),
      buildConfig('secret'),
    );

    const result = await service.verifyEmail({ email: 'student@example.com', code: '123456' });

    expect(verifyCode).toHaveBeenCalledWith('student@example.com', '123456');
    expect(result).toBeUndefined();
  });
});

describe('AuthService.signUp', () => {
  it('rejects when the email was never verified', async () => {
    const consumeVerification = jest
      .fn()
      .mockRejectedValue(new ConflictDomainException('이메일 인증을 먼저 완료해주세요.'));
    const register = jest.fn();
    const userService = { register } as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const service = new AuthService(
      userService,
      adminService,
      buildJwtService(),
      buildMailService(),
      buildEmailVerificationService({ consumeVerification }),
      buildConfig('secret'),
    );
    const dto: SignUpDto = {
      email: 'student@example.com',
      password: '12341234!!',
      firstName: 'GILDONG',
      lastName: 'HONG',
      nationality: 'KOR',
      birthDate: '1995-03-21',
      agreedToTerms: true,
      agreedToPrivacyPolicy: true,
      agreedToPassportProcessing: true,
    };

    await expect(service.signUp(dto)).rejects.toThrow(ConflictDomainException);
    expect(register).not.toHaveBeenCalled();
  });

  it('registers the account and issues tokens once the email was verified', async () => {
    const verifiedAt = new Date('2026-01-01T00:00:00.000Z');
    const consumeVerification = jest.fn().mockResolvedValue(verifiedAt);
    const register = jest.fn().mockResolvedValue(buildUser());
    const userService = { register } as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const jwtService = buildJwtService();
    const service = new AuthService(
      userService,
      adminService,
      jwtService,
      buildMailService(),
      buildEmailVerificationService({ consumeVerification }),
      buildConfig('secret'),
    );
    const dto: SignUpDto = {
      email: 'student@example.com',
      password: '12341234!!',
      firstName: 'GILDONG',
      lastName: 'HONG',
      nationality: 'KOR',
      birthDate: '1995-03-21',
      agreedToTerms: true,
      agreedToPrivacyPolicy: true,
      agreedToPassportProcessing: true,
    };

    const result = await service.signUp(dto);

    expect(consumeVerification).toHaveBeenCalledWith('student@example.com');
    expect(register).toHaveBeenCalledWith(expect.objectContaining({ emailVerifiedAt: verifiedAt }));
    expect(result.accessToken).toBe('signed-token');
    expect(result.role).toBe(Role.USER);
  });

  it('maps agreedToVoiceDataAiTraining to a timestamp when true, and to null when omitted', async () => {
    const register = jest.fn().mockResolvedValue(buildUser());
    const userService = { register } as unknown as UserService;
    const adminService = {} as unknown as AdminService;
    const service = new AuthService(
      userService,
      adminService,
      buildJwtService(),
      buildMailService(),
      buildEmailVerificationService(),
      buildConfig('secret'),
    );
    const baseDto: SignUpDto = {
      email: 'student@example.com',
      password: '12341234!!',
      firstName: 'GILDONG',
      lastName: 'HONG',
      nationality: 'KOR',
      birthDate: '1995-03-21',
      agreedToTerms: true,
      agreedToPrivacyPolicy: true,
      agreedToPassportProcessing: true,
    };

    await service.signUp({ ...baseDto, agreedToVoiceDataAiTraining: true });
    await service.signUp(baseDto);

    const [firstCall, secondCall] = register.mock.calls as {
      voiceDataAiTrainingAgreedAt: Date | null;
    }[][];
    expect(firstCall[0].voiceDataAiTrainingAgreedAt).toBeInstanceOf(Date);
    expect(secondCall[0].voiceDataAiTrainingAgreedAt).toBeNull();
  });
});
