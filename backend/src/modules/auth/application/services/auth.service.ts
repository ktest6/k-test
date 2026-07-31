import { timingSafeEqual } from 'node:crypto';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { JwtService, JwtSignOptions } from '@nestjs/jwt';
import { appConfig } from '../../../../config/configuration';
import { UnauthorizedDomainException } from '../../../../common/exceptions/domain.exception';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
import { AdminSignUpDto } from '../dto/admin-sign-up.dto';
import { AuthResponseDto } from '../dto/auth-response.dto';
import { CheckEmailResponseDto } from '../dto/check-email-response.dto';
import { SignInDto } from '../dto/sign-in.dto';
import { SignUpDto } from '../dto/sign-up.dto';

interface JwtPayload {
  sub: string;
  email: string;
  role: string;
  type?: 'refresh';
}

@Injectable()
export class AuthService {
  constructor(
    private readonly userService: UserService,
    private readonly jwtService: JwtService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async checkEmailAvailability(email: string): Promise<CheckEmailResponseDto> {
    const taken = await this.userService.existsByEmail(email);
    return { available: !taken };
  }

  async signUp(dto: SignUpDto): Promise<AuthResponseDto> {
    const now = new Date();
    const user = await this.userService.register({
      email: dto.email,
      password: dto.password,
      firstName: dto.firstName,
      lastName: dto.lastName,
      nationality: dto.nationality,
      birthDate: dto.birthDate,
      idType: dto.idType,
      idNumber: dto.idNumber,
      companyCode: dto.companyCode,
      termsAgreedAt: now,
      privacyAgreedAt: now,
    });
    return this.toAuthResponse(user);
  }

  /**
   * 관리자 계정 생성. 로그인 사용자 검증(@Roles(ADMIN)) 대신 공유 비밀값으로
   * 게이트를 건다 — 그래야 "첫 관리자를 누가 만드나"라는 부트스트랩 문제가
   * 없다. 이후 관리자 관리 기능(비활성화, 권한 회수 등)은 별도로 ADMIN 전용
   * 엔드포인트로 만들면 된다.
   */
  async adminSignUp(dto: AdminSignUpDto): Promise<AuthResponseDto> {
    if (!this.isValidAdminSecret(dto.adminSecret)) {
      throw new UnauthorizedDomainException('관리자 계정 생성 비밀값이 올바르지 않습니다.');
    }

    const user = await this.userService.registerAdmin({
      email: dto.email,
      password: dto.password,
      firstName: dto.firstName,
      lastName: dto.lastName,
    });
    return this.toAuthResponse(user);
  }

  async signIn(dto: SignInDto): Promise<AuthResponseDto> {
    const user = await this.userService.verifyCredentials(dto.email, dto.password);
    return this.toAuthResponse(user);
  }

  async refreshSession(refreshToken: string): Promise<AuthResponseDto> {
    let payload: JwtPayload;
    try {
      payload = await this.jwtService.verifyAsync<JwtPayload>(refreshToken, {
        secret: this.config.jwt.refreshSecret,
      });
    } catch {
      throw new UnauthorizedDomainException('유효하지 않거나 만료된 리프레시 토큰입니다.');
    }
    if (payload.type !== 'refresh') {
      throw new UnauthorizedDomainException('리프레시 토큰이 아닙니다.');
    }

    const user = await this.userService.findById(payload.sub);
    return this.toAuthResponse(user);
  }

  private toAuthResponse(user: User): AuthResponseDto {
    const { accessToken, refreshToken, expiresIn } = this.issueTokens(user);
    return {
      accessToken,
      refreshToken,
      expiresIn,
      userId: user.id,
      email: user.email,
      role: user.role,
    };
  }

  private issueTokens(user: User): {
    accessToken: string;
    refreshToken: string;
    expiresIn: number;
  } {
    const payload: JwtPayload = { sub: user.id, email: user.email, role: user.role };

    const accessExpiresIn = this.config.jwt
      .accessExpiresIn as unknown as JwtSignOptions['expiresIn'];
    const refreshExpiresIn = this.config.jwt
      .refreshExpiresIn as unknown as JwtSignOptions['expiresIn'];

    const accessToken = this.jwtService.sign(payload, {
      secret: this.config.jwt.accessSecret,
      expiresIn: accessExpiresIn,
    });
    const refreshToken = this.jwtService.sign(
      { ...payload, type: 'refresh' },
      { secret: this.config.jwt.refreshSecret, expiresIn: refreshExpiresIn },
    );

    const decoded = this.jwtService.decode<{ exp: number; iat: number }>(accessToken);
    const expiresIn = decoded.exp - decoded.iat;

    return { accessToken, refreshToken, expiresIn };
  }

  /** 길이가 다르면 timingSafeEqual이 던지므로 그 경우는 그냥 불일치로 처리. */
  private isValidAdminSecret(provided: string): boolean {
    const expected = Buffer.from(this.config.admin.signupSecret);
    const actual = Buffer.from(provided);
    if (expected.length !== actual.length) {
      return false;
    }
    return timingSafeEqual(expected, actual);
  }
}
