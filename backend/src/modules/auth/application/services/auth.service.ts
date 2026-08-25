import { timingSafeEqual } from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { JwtService, JwtSignOptions } from '@nestjs/jwt';
import { appConfig } from '../../../../config/configuration';
import { Role } from '../../../../common/enums/role.enum';
import {
  ConflictDomainException,
  UnauthorizedDomainException,
} from '../../../../common/exceptions/domain.exception';
import { operationFailed } from '../../../../common/exceptions/error-messages';
import { describeError } from '../../../../common/utils/describe-error.util';
import { MailService } from '../../../../infrastructure/mail/mail.service';
import { AdminService } from '../../../admin/application/services/admin.service';
import { UserService } from '../../../user/application/services/user.service';
import { AdminSignUpDto } from '../dto/admin-sign-up.dto';
import { AuthResponseDto } from '../dto/auth-response.dto';
import { CheckEmailResponseDto } from '../dto/check-email-response.dto';
import { SendCodeDto } from '../dto/send-code.dto';
import { SignInDto } from '../dto/sign-in.dto';
import { SignUpDto } from '../dto/sign-up.dto';
import { VerifyEmailDto } from '../dto/verify-email.dto';
import { EmailVerificationService } from './email-verification.service';

interface JwtPayload {
  sub: string;
  email: string;
  role: Role;
  type?: 'refresh';
}

interface Account {
  id: string;
  email: string;
}

@Injectable()
export class AuthService {
  private readonly logger = new Logger(AuthService.name);

  constructor(
    private readonly userService: UserService,
    private readonly adminService: AdminService,
    private readonly jwtService: JwtService,
    private readonly mailService: MailService,
    private readonly emailVerificationService: EmailVerificationService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async checkEmailAvailability(email: string): Promise<CheckEmailResponseDto> {
    const taken = await this.userService.existsByEmail(email);
    return { available: !taken };
  }

  /**
   * 가입 전에 이메일로 인증코드를 보낸다 — 최초 발송/재발송 공용. 메일 발송
   * 자체가 이 API의 목적이라, 실패를 조용히 삼키면 "성공" 응답을 받은 사용자가
   * 오지 않을 메일을 기다리게 된다. 그래서 발송 실패는 명확한 에러로 알린다.
   */
  async sendVerificationCode(dto: SendCodeDto): Promise<void> {
    const code = await this.emailVerificationService.sendCode(dto.email);
    try {
      await this.mailService.sendVerificationCode(dto.email, code);
    } catch (err) {
      this.logger.warn(`인증 메일 발송 실패 (email=${dto.email}): ${describeError(err)}`);
      throw new ConflictDomainException(operationFailed('send the verification email'));
    }
  }

  async verifyEmail(dto: VerifyEmailDto): Promise<void> {
    await this.emailVerificationService.verifyCode(dto.email, dto.code);
  }

  /**
   * 이메일 인증이 이미 끝난 뒤에만 호출된다(프론트 흐름: 이메일 인증 → 나머지 정보
   * 입력 → 최종 가입). 인증 안 된 이메일이면 여기서 막힌다. 가입 시점엔 이미 본인
   * 확인이 끝난 상태라 별도 로그인 없이 바로 토큰을 발급한다.
   */
  async signUp(dto: SignUpDto): Promise<AuthResponseDto> {
    const emailVerifiedAt = await this.emailVerificationService.consumeVerification(dto.email);
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
      passportProcessingAgreedAt: now,
      emailVerifiedAt,
      voiceDataAiTrainingAgreedAt: dto.agreedToVoiceDataAiTraining ? now : null,
    });
    return this.toAuthResponse(user, Role.USER);
  }

  /**
   * 관리자 계정 생성. 로그인 사용자 검증(@Roles(ADMIN)) 대신 공유 비밀값으로
   * 게이트를 건다 — 그래야 "첫 관리자를 누가 만드나"라는 부트스트랩 문제가
   * 없다. 이후 관리자 관리 기능(비활성화, 권한 회수 등)은 별도로 ADMIN 전용
   * 엔드포인트로 만들면 된다. 관리자는 tb_admin에 별도로 저장된다(tb_user와
   * 완전히 분리) — 신분증/약관동의 같은 응시자 전용 필드는 아예 없다.
   */
  async adminSignUp(dto: AdminSignUpDto): Promise<AuthResponseDto> {
    if (!this.isValidAdminSecret(dto.adminSecret)) {
      throw new UnauthorizedDomainException('The admin account creation secret is incorrect.');
    }

    const admin = await this.adminService.register({
      email: dto.email,
      password: dto.password,
      name: dto.name,
    });
    return this.toAuthResponse(admin, Role.ADMIN);
  }

  async signIn(dto: SignInDto): Promise<AuthResponseDto> {
    const user = await this.userService.verifyCredentials(dto.email, dto.password);
    return this.toAuthResponse(user, Role.USER);
  }

  async adminSignIn(dto: SignInDto): Promise<AuthResponseDto> {
    const admin = await this.adminService.verifyCredentials(dto.email, dto.password);
    return this.toAuthResponse(admin, Role.ADMIN);
  }

  /**
   * 테스트 전용 유틸리티(TestModule)에서만 호출한다 — 이미 존재가 보장된
   * 계정(가입/이메일 인증 절차를 거치지 않고 만들어진 테스트 계정 포함)에
   * 로그인 없이 바로 토큰을 발급한다. 관리자 role은 지원하지 않는다.
   */
  issueTestAccessToken(userId: string, email: string): AuthResponseDto {
    return this.toAuthResponse({ id: userId, email }, Role.USER);
  }

  async refreshSession(refreshToken: string): Promise<AuthResponseDto> {
    let payload: JwtPayload;
    try {
      payload = await this.jwtService.verifyAsync<JwtPayload>(refreshToken, {
        secret: this.config.jwt.refreshSecret,
      });
    } catch {
      throw new UnauthorizedDomainException('Invalid or expired refresh token.');
    }
    if (payload.type !== 'refresh') {
      throw new UnauthorizedDomainException('This is not a refresh token.');
    }

    if (payload.role === Role.ADMIN) {
      const admin = await this.adminService.findById(payload.sub);
      return this.toAuthResponse(admin, Role.ADMIN);
    }
    const user = await this.userService.findById(payload.sub);
    return this.toAuthResponse(user, Role.USER);
  }

  private toAuthResponse(account: Account, role: Role): AuthResponseDto {
    const { accessToken, refreshToken, expiresIn } = this.issueTokens(account, role);
    return {
      accessToken,
      refreshToken,
      expiresIn,
      userId: account.id,
      email: account.email,
      role,
    };
  }

  private issueTokens(
    account: Account,
    role: Role,
  ): {
    accessToken: string;
    refreshToken: string;
    expiresIn: number;
  } {
    const payload: JwtPayload = { sub: account.id, email: account.email, role };

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
