import { Body, Controller, HttpCode, HttpStatus, Post } from '@nestjs/common';
import { ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Public } from '../../../common/decorators/public.decorator';
import { AuthService } from '../application/services/auth.service';
import { AdminSignUpDto } from '../application/dto/admin-sign-up.dto';
import { AuthResponseDto } from '../application/dto/auth-response.dto';
import { SignInDto } from '../application/dto/sign-in.dto';

@ApiTags('Admin - Auth')
@ApiCommonErrorResponses()
@Controller('auth/admin')
export class AdminAuthController {
  constructor(private readonly authService: AuthService) {}

  @Public()
  @Post('sign-up')
  @ApiOperation({
    summary: '관리자 계정 생성(확인용)',
    description:
      '로그인 없이(@Public) 호출하지만, 서버 env(ADMIN_SIGNUP_SECRET)와 일치하는 adminSecret이 ' +
      '있어야 생성된다 — 첫 관리자를 만들 방법이 없다는 부트스트랩 문제를 이렇게 푼다. ' +
      '신분증/약관동의 같은 응시자 전용 필드는 받지 않는다.',
  })
  @ApiStandardResponse(AuthResponseDto, { status: 201, message: '관리자 계정 생성 완료' })
  adminSignUp(@Body() dto: AdminSignUpDto): Promise<AuthResponseDto> {
    return this.authService.adminSignUp(dto);
  }

  @Public()
  @Post('sign-in')
  @HttpCode(HttpStatus.OK)
  @ApiOperation({
    summary: '관리자 로그인',
    description:
      '관리자는 tb_admin에 별도로 저장되어 있어 응시자 로그인(sign-in)과 다른 엔드포인트를 쓴다.',
  })
  @ApiStandardResponse(AuthResponseDto, { message: '관리자 로그인 성공' })
  adminSignIn(@Body() dto: SignInDto): Promise<AuthResponseDto> {
    return this.authService.adminSignIn(dto);
  }
}
