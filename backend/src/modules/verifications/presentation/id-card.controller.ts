import { Body, Controller, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { RequestIdCardUploadUrlDto } from '../application/dto/request-id-card-upload-url.dto';
import { UploadUrlResponseDto } from '../application/dto/upload-url-response.dto';
import { VerifyIdCardResponseDto } from '../application/dto/verify-id-card-response.dto';
import { VerifyIdCardDto } from '../application/dto/verify-id-card.dto';
import { IdCardUploadUrlService } from '../application/services/id-card-upload-url.service';
import { IdCardVerificationService } from '../application/services/id-card-verification.service';

/**
 * /verifications 아래 인증 타입별 고정 경로 중 하나 — 신분증/얼굴 대조.
 * 다른 인증 타입(예: 이어폰 착용 여부 확인)을 추가할 때는 이 컨트롤러를
 * 건드리지 않고 형제 컨트롤러(예: earphone.controller.ts, @Controller
 * ('verifications/earphone'))를 새로 만들면 된다.
 */
@ApiBearerAuth()
@ApiTags('Verifications')
@ApiCommonErrorResponses()
@Controller('verifications/id-card')
export class IdCardController {
  constructor(
    private readonly idCardUploadUrlService: IdCardUploadUrlService,
    private readonly idCardVerificationService: IdCardVerificationService,
  ) {}

  @Post('upload-url')
  @ApiOperation({
    summary: '신분증 인증 이미지 업로드용 signed URL 발급',
    description:
      '프론트는 이 URL로 Supabase Storage에 직접 업로드한다 (백엔드를 거치지 않음). ' +
      '경로는 서버가 직접 정하므로(요청자 소유 폴더로 고정) 다른 사용자 경로로 업로드할 수 없다.',
  })
  @ApiStandardResponse(UploadUrlResponseDto, { status: 201, message: '업로드 URL 발급 완료' })
  createUploadUrl(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: RequestIdCardUploadUrlDto,
  ): Promise<UploadUrlResponseDto> {
    return this.idCardUploadUrlService.createUploadUrl(user.id, dto);
  }

  @Post('verify')
  @ApiOperation({
    summary: '시험 시작 전 본인인증 (신분증-얼굴 대조)',
    description:
      '신분증/웹캠 이미지 자체는 프론트가 upload-url로 발급받은 signed URL로 Supabase Storage에 ' +
      '직접 업로드한 뒤, 그 경로(idCardPath/facePath)만 이 API로 전달한다.',
  })
  @ApiStandardResponse(VerifyIdCardResponseDto, {
    status: 201,
    message: '본인인증 요청 접수 완료',
  })
  verify(
    @CurrentUser() user: AuthenticatedUser,
    @Body() dto: VerifyIdCardDto,
  ): Promise<VerifyIdCardResponseDto> {
    return this.idCardVerificationService.verify(user.id, dto);
  }
}
