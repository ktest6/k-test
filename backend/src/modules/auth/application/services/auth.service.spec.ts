import { JwtService } from '@nestjs/jwt';
import { UnauthorizedDomainException } from '../../../../common/exceptions/domain.exception';
import { Role } from '../../../../common/enums/role.enum';
import { AppConfig } from '../../../../config/configuration';
import { Admin } from '../../../admin/domain/entities/admin.entity';
import { AdminService } from '../../../admin/application/services/admin.service';
import { UserService } from '../../../user/application/services/user.service';
import { AdminSignUpDto } from '../dto/admin-sign-up.dto';
import { SignInDto } from '../dto/sign-in.dto';
import { AuthService } from './auth.service';

function buildConfig(signupSecret: string): AppConfig {
  return {
    env: 'test',
    port: 3000,
    corsOrigin: '*',
    swaggerEnabled: false,
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
    fastApi: { url: '' },
    assessment: { url: '', apiKey: '' },
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
    const service = new AuthService(userService, adminService, jwtService, buildConfig('secret'));
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
    const service = new AuthService(userService, adminService, jwtService, buildConfig('secret'));

    await expect(
      service.adminSignIn({ email: 'admin1@test.com', password: 'wrong' }),
    ).rejects.toThrow(UnauthorizedDomainException);
  });
});
