import { Body, Controller, Get, HttpCode, HttpStatus, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Public } from '../../../common/decorators/public.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { AuthService } from '../application/services/auth.service';
import { AuthResponseDto } from '../application/dto/auth-response.dto';
import { CheckEmailQueryDto } from '../application/dto/check-email-query.dto';
import { CheckEmailResponseDto } from '../application/dto/check-email-response.dto';
import { MeResponseDto } from '../application/dto/me-response.dto';
import { RefreshTokenDto } from '../application/dto/refresh-token.dto';
import { SendCodeDto } from '../application/dto/send-code.dto';
import { SendCodeResponseDto } from '../application/dto/send-code-response.dto';
import { SignInDto } from '../application/dto/sign-in.dto';
import { SignOutResponseDto } from '../application/dto/sign-out-response.dto';
import { SignUpDto } from '../application/dto/sign-up.dto';
import { VerifyEmailDto } from '../application/dto/verify-email.dto';
import { VerifyEmailResponseDto } from '../application/dto/verify-email-response.dto';

@ApiTags('Auth')
@ApiCommonErrorResponses()
@Controller('auth')
export class AuthController {
  constructor(private readonly authService: AuthService) {}

  @Public()
  @Get('check-email')
  @ApiOperation({
    summary: '이메일 중복 확인 (부가 기능)',
    description:
      '타이핑 중 즉시 피드백용 조회 API. 실제 가입 흐름에서 중복 체크는 email/send-code가 다시 하므로, 프론트가 이 호출을 생략해도 안전하다.',
  })
  @ApiStandardResponse(CheckEmailResponseDto, { message: 'Email availability checked' })
  checkEmail(@Query() query: CheckEmailQueryDto): Promise<CheckEmailResponseDto> {
    return this.authService.checkEmailAvailability(query.email);
  }

  @Public()
  @Post('email/send-code')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({
    summary: '회원가입 1단계: 이메일 인증번호 발송 (최초 발송/재발송 공용)',
    description:
      '이미 가입된 이메일이면 409. 아직 계정이 없으므로 인증 상태는 이메일 기준으로 임시 보관된다.',
  })
  @ApiStandardResponse(SendCodeResponseDto, { message: 'Verification code sent' })
  async sendCode(@Body() dto: SendCodeDto): Promise<SendCodeResponseDto> {
    await this.authService.sendVerificationCode(dto);
    return {};
  }

  @Public()
  @Post('email/verify')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({
    summary: '회원가입 2단계: 이메일 인증번호 확인',
    description:
      '계정 생성 전 단계라 토큰은 발급하지 않는다. 확인되면 이 이메일로 가입을 진행할 수 있다.',
  })
  @ApiStandardResponse(VerifyEmailResponseDto, { message: 'Email verified' })
  async verifyEmail(@Body() dto: VerifyEmailDto): Promise<VerifyEmailResponseDto> {
    await this.authService.verifyEmail(dto);
    return {};
  }

  @Public()
  @Post('sign-up')
  @ApiOperation({
    summary: '회원가입 3단계: 계정 생성 (이메일 인증 완료 후)',
    description:
      'email/verify로 인증되지 않은 이메일이면 409. 인증된 이메일이면 계정을 만들고 바로 로그인 토큰을 발급한다(별도 로그인 불필요).',
  })
  @ApiStandardResponse(AuthResponseDto, { status: 201, message: 'Sign-up completed' })
  signUp(@Body() dto: SignUpDto): Promise<AuthResponseDto> {
    return this.authService.signUp(dto);
  }

  @Public()
  @Post('sign-in')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: '로그인' })
  @ApiStandardResponse(AuthResponseDto, { message: 'Login successful' })
  signIn(@Body() dto: SignInDto): Promise<AuthResponseDto> {
    return this.authService.signIn(dto);
  }

  @Public()
  @Post('refresh')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: '토큰 갱신' })
  @ApiStandardResponse(AuthResponseDto, { message: 'Token refreshed' })
  refresh(@Body() dto: RefreshTokenDto): Promise<AuthResponseDto> {
    return this.authService.refreshSession(dto.refreshToken);
  }

  @ApiBearerAuth()
  @Post('sign-out')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({
    summary: '로그아웃',
    description:
      '자체 발급 JWT는 상태를 저장하지 않으므로(stateless) 서버가 할 일은 없다 — 클라이언트가 보유한 토큰을 폐기하면 된다. 엔드포인트는 프론트엔드 흐름의 대칭성을 위해 유지한다.',
  })
  @ApiStandardResponse(SignOutResponseDto, { message: 'Signed out' })
  signOut(): SignOutResponseDto {
    return {};
  }

  @ApiBearerAuth()
  @Get('me')
  @ApiOperation({ summary: '현재 로그인한 사용자 정보' })
  @ApiStandardResponse(MeResponseDto, { message: 'Account info retrieved' })
  me(@CurrentUser() user: AuthenticatedUser): MeResponseDto {
    return user;
  }
}
