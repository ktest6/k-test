import { JwtService } from '@nestjs/jwt';
import { UnauthorizedDomainException } from '../../../../common/exceptions/domain.exception';
import { Role } from '../../../../common/enums/role.enum';
import { AppConfig } from '../../../../config/configuration';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
import { AdminSignUpDto } from '../dto/admin-sign-up.dto';
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
  };
}

function buildAdminUser(): User {
  return new User(
    '1',
    'admin1@test.com',
    'GILDONG',
    'HONG',
    Role.ADMIN,
    null,
    null,
    null,
    null,
    null,
    null,
    null,
    0,
    null,
    new Date(),
  );
}

function buildDto(overrides: Partial<AdminSignUpDto> = {}): AdminSignUpDto {
  return {
    email: 'admin1@test.com',
    password: '12341234!!',
    firstName: 'GILDONG',
    lastName: 'HONG',
    adminSecret: 'correct-secret-value',
    ...overrides,
  };
}

describe('AuthService.adminSignUp', () => {
  function buildService(signupSecret = 'correct-secret-value') {
    const registerAdmin = jest.fn().mockResolvedValue(buildAdminUser());
    const userService = { registerAdmin } as unknown as UserService;
    const jwtService = {
      sign: jest.fn().mockReturnValue('signed-token'),
      decode: jest.fn().mockReturnValue({ iat: 0, exp: 3600 }),
    } as unknown as JwtService;

    const service = new AuthService(userService, jwtService, buildConfig(signupSecret));
    return { service, registerAdmin };
  }

  it('rejects when the admin secret does not match', async () => {
    const { service, registerAdmin } = buildService('correct-secret-value');

    await expect(service.adminSignUp(buildDto({ adminSecret: 'wrong-secret' }))).rejects.toThrow(
      UnauthorizedDomainException,
    );
    expect(registerAdmin).not.toHaveBeenCalled();
  });

  it('rejects when the admin secret has a different length', async () => {
    const { service, registerAdmin } = buildService('correct-secret-value');

    await expect(service.adminSignUp(buildDto({ adminSecret: 'short' }))).rejects.toThrow(
      UnauthorizedDomainException,
    );
    expect(registerAdmin).not.toHaveBeenCalled();
  });

  it('creates the admin and issues tokens when the secret matches', async () => {
    const { service, registerAdmin } = buildService('correct-secret-value');

    const result = await service.adminSignUp(buildDto());

    expect(registerAdmin).toHaveBeenCalledWith({
      email: 'admin1@test.com',
      password: '12341234!!',
      firstName: 'GILDONG',
      lastName: 'HONG',
    });
    expect(result.accessToken).toBe('signed-token');
    expect(result.role).toBe(Role.ADMIN);
  });
});
