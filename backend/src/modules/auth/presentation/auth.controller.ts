import { Body, Controller, Get, HttpCode, HttpStatus, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Public } from '../../../common/decorators/public.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { AuthService } from '../application/services/auth.service';
import { AuthResponseDto } from '../application/dto/auth-response.dto';
import { CheckEmailQueryDto } from '../application/dto/check-email-query.dto';
import { CheckEmailResponseDto } from '../application/dto/check-email-response.dto';
import { RefreshTokenDto } from '../application/dto/refresh-token.dto';
import { SignInDto } from '../application/dto/sign-in.dto';
import { SignUpDto } from '../application/dto/sign-up.dto';

@ApiTags('Auth')
@Controller('auth')
export class AuthController {
  constructor(private readonly authService: AuthService) {}

  @Public()
  @Get('check-email')
  @ApiOperation({ summary: '회원가입 1단계: 이메일 중복 확인' })
  checkEmail(@Query() query: CheckEmailQueryDto): Promise<CheckEmailResponseDto> {
    return this.authService.checkEmailAvailability(query.email);
  }

  @Public()
  @Post('sign-up')
  @ApiOperation({ summary: '회원가입 완료 (계정 + 신원 정보 + 약관 동의)' })
  signUp(@Body() dto: SignUpDto): Promise<AuthResponseDto> {
    return this.authService.signUp(dto);
  }

  @Public()
  @Post('sign-in')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: '로그인' })
  signIn(@Body() dto: SignInDto): Promise<AuthResponseDto> {
    return this.authService.signIn(dto);
  }

  @Public()
  @Post('refresh')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({ summary: '토큰 갱신' })
  refresh(@Body() dto: RefreshTokenDto): Promise<AuthResponseDto> {
    return this.authService.refreshSession(dto.refreshToken);
  }

  @ApiBearerAuth()
  @Post('sign-out')
  @HttpCode(HttpStatus.NO_CONTENT)
  @ApiOperation({
    summary: '로그아웃',
    description:
      '자체 발급 JWT는 상태를 저장하지 않으므로(stateless) 서버가 할 일은 없다 — 클라이언트가 보유한 토큰을 폐기하면 된다. 엔드포인트는 프론트엔드 흐름의 대칭성을 위해 유지한다.',
  })
  signOut(): void {
    return;
  }

  @ApiBearerAuth()
  @Get('me')
  @ApiOperation({ summary: '현재 로그인한 사용자 정보' })
  me(@CurrentUser() user: AuthenticatedUser): AuthenticatedUser {
    return user;
  }
}
