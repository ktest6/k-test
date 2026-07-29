import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { JwtService, JwtSignOptions } from '@nestjs/jwt';
import { appConfig } from '../../../../config/configuration';
import { UnauthorizedDomainException } from '../../../../common/exceptions/domain.exception';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
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
      name: dto.name,
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
}
