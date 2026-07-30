import { Body, Controller, Get, Param, ParseUUIDPipe, Post, Query } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { InitiateVerificationResponseDto } from '../application/dto/initiate-verification-response.dto';
import { InitiateVerificationDto } from '../application/dto/initiate-verification.dto';
import { VerificationLogResponseDto } from '../application/dto/verification-log-response.dto';
import { VerificationResultDto } from '../application/dto/verification-result.dto';
import { VerificationStatusResponseDto } from '../application/dto/verification-status-response.dto';
import { VerifyChallengeDto } from '../application/dto/verify-challenge.dto';
import { VerifyPeriodicDto } from '../application/dto/verify-periodic.dto';
import { IdentityVerificationService } from '../application/services/identity-verification.service';

@ApiBearerAuth()
@ApiTags('Identity Verification')
@ApiCommonErrorResponses()
@Controller('identity-verification')
export class IdentityVerificationController {
  constructor(private readonly identityVerificationService: IdentityVerificationService) {}

  @Post('pre-exam/initiate')
  @ApiOperation({ summary: '시험 시작 전 본인인증 세션 생성' })
  @ApiStandardResponse(InitiateVerificationResponseDto, {
    status: 201,
    message: '본인인증 세션 생성 완료',
  })
  initiatePreExam(
    @Body() dto: InitiateVerificationDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<InitiateVerificationResponseDto> {
    return this.identityVerificationService.initiatePreExam(dto.submissionId, user.id);
  }

  @Post('pre-exam/verify')
  @ApiOperation({ summary: '시험 시작 전 본인인증 결과 제출' })
  @ApiStandardResponse(VerificationResultDto, { status: 201, message: '본인인증 결과 제출 완료' })
  verifyPreExam(
    @Body() dto: VerifyChallengeDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<VerificationResultDto> {
    return this.identityVerificationService.verifyPreExam(dto, user.id);
  }

  @Get('periodic/status')
  @ApiOperation({ summary: '응시 중 재인증이 지금 필요한지 조회 (폴링용)' })
  @ApiStandardResponse(VerificationStatusResponseDto, { message: '재인증 필요 여부 조회 완료' })
  getPeriodicStatus(
    @Query('submissionId', new ParseUUIDPipe()) submissionId: string,
  ): Promise<VerificationStatusResponseDto> {
    return this.identityVerificationService.getPeriodicStatus(submissionId);
  }

  @Post('periodic/verify')
  @ApiOperation({ summary: '응시 중 랜덤/주기 재인증 결과 제출' })
  @ApiStandardResponse(VerificationResultDto, { status: 201, message: '재인증 결과 제출 완료' })
  verifyPeriodic(
    @Body() dto: VerifyPeriodicDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<VerificationResultDto> {
    return this.identityVerificationService.verifyPeriodic(dto, user.id);
  }

  @Get('sessions/:submissionId/logs')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '본인인증 감사 로그 조회 (관리자 전용)' })
  @ApiStandardResponse(VerificationLogResponseDto, {
    isArray: true,
    message: '본인인증 로그 조회 성공',
  })
  getLogs(
    @Param('submissionId', new ParseUUIDPipe()) submissionId: string,
  ): Promise<VerificationLogResponseDto[]> {
    return this.identityVerificationService.getLogs(submissionId);
  }
}
