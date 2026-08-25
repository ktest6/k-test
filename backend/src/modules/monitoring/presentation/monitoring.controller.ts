import {
  BadRequestException,
  Body,
  Controller,
  Param,
  Post,
  UploadedFile,
  UseInterceptors,
} from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { ApiBearerAuth, ApiBody, ApiConsumes, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { AnalyzeFrameDto } from '../application/dto/analyze-frame.dto';
import { AttachClipDto } from '../application/dto/attach-clip.dto';
import { ClipUploadUrlResponseDto } from '../application/dto/clip-upload-url-response.dto';
import { MonitoringAnalyzeResponseDto } from '../application/dto/monitoring-analyze-response.dto';
import { ProctoringEventResponseDto } from '../application/dto/proctoring-event-response.dto';
import { RequestClipUploadUrlDto } from '../application/dto/request-clip-upload-url.dto';
import { ReportViolationResponseDto } from '../application/dto/report-violation-response.dto';
import { ReportViolationDto } from '../application/dto/report-violation.dto';
import { MonitoringService } from '../application/services/monitoring.service';
import { toEventDto } from './proctoring-event.mapper';

const MAX_FRAME_SIZE_BYTES = 5 * 1024 * 1024;

@ApiBearerAuth()
@ApiTags('Monitoring')
@ApiCommonErrorResponses()
@Controller('exam-sessions/:examSessionId/monitoring')
export class MonitoringController {
  constructor(private readonly monitoringService: MonitoringService) {}

  @Post('analyze')
  @UseInterceptors(FileInterceptor('current_image', { limits: { fileSize: MAX_FRAME_SIZE_BYTES } }))
  @ApiConsumes('multipart/form-data')
  @ApiBody({
    schema: {
      type: 'object',
      required: ['current_image', 'capturedAt', 'elapsedMs', 'captureSequence'],
      properties: {
        current_image: { type: 'string', format: 'binary', description: '현재 웹캠 프레임' },
        capturedAt: { type: 'string', example: '2026-08-04T13:05:00+09:00' },
        elapsedMs: { type: 'integer', example: 300000 },
        captureSequence: { type: 'integer', example: 60 },
        runIdentityCheck: { type: 'boolean', default: false },
      },
    },
  })
  @ApiOperation({
    summary: '웹캠 프레임 분석 요청 (부정행위 감지)',
    description:
      '시험 응시 중 주기적으로 웹캠 프레임을 올리면 모니터링 서비스에 분석을 요청하고, 탐지된 의심 행동을 기록한다. ' +
      '동일인 검사(runIdentityCheck)용 기준 얼굴 이미지는 프론트가 보내지 않는다 — 본인인증 때 저장된 사진을 서버가 알아서 붙인다. ' +
      '모니터링 서비스가 응답하지 않아도 이 API 자체는 실패하지 않는다(로그만 남기고 이상 없음으로 처리).',
  })
  @ApiStandardResponse(MonitoringAnalyzeResponseDto, {
    status: 201,
    message: 'Frame analysis completed',
  })
  async analyze(
    @Param('examSessionId') examSessionId: string,
    @UploadedFile() currentImage: Express.Multer.File,
    @Body() dto: AnalyzeFrameDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<MonitoringAnalyzeResponseDto> {
    if (!currentImage) {
      throw new BadRequestException('The current_image file is required.');
    }

    const result = await this.monitoringService.analyze(examSessionId, user.id, dto, {
      buffer: currentImage.buffer,
      filename: currentImage.originalname,
      contentType: currentImage.mimetype,
    });

    return {
      severity: result.severity,
      decision: result.decision,
      createClip: result.createClip,
      eventCount: result.eventCount,
      recordedEvents: result.recordedEvents.map(toEventDto),
    };
  }

  @Post('violations')
  @ApiOperation({
    summary: '브라우저 감지 부정행위 신고 (탭 이탈/포커스 이탈/붙여넣기/듀얼 모니터 등)',
    description:
      'AI 모니터링(analyze)과 별개로, 프런트가 브라우저 이벤트로 직접 감지한 위반을 기록한다. ' +
      '웹캠 프레임이 없는 신호라 스냅샷은 남기지 않는다. 종류 무관하게 같은 violationType이 누적 ' +
      '2회부터 자동으로 세션이 실격 처리되고(종류별로 각각 따로 셈), 응답의 sessionStatus로 바로 ' +
      '확인할 수 있다(별도 상태 조회 필요 없음).',
  })
  @ApiStandardResponse(ReportViolationResponseDto, { status: 201, message: 'Violation reported' })
  async reportViolation(
    @Param('examSessionId') examSessionId: string,
    @Body() dto: ReportViolationDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ReportViolationResponseDto> {
    const { event, sessionStatus } = await this.monitoringService.reportViolation(
      examSessionId,
      user.id,
      dto,
    );
    return { ...toEventDto(event), sessionStatus };
  }

  @Post('events/:eventId/clip-upload-url')
  @ApiOperation({
    summary: '부정행위 이벤트 영상 클립 업로드용 signed URL 발급',
    description:
      'AI가 createClip:true로 판단한 순간의 웹캠 영상 클립을 올릴 URL을 발급한다. 백엔드는 정지 프레임만 받으므로 ' +
      '영상 자체는 프런트가 녹화해서 올려야 한다. 프론트는 이 URL로 Supabase Storage에 직접 업로드한 뒤, 응답의 ' +
      'path를 그대로 클립 첨부(POST .../clip)의 clipPath로 전달하면 된다.',
  })
  @ApiStandardResponse(ClipUploadUrlResponseDto, { status: 201, message: 'Upload URL issued' })
  createClipUploadUrl(
    @Param('examSessionId') examSessionId: string,
    @Param('eventId') eventId: string,
    @Body() dto: RequestClipUploadUrlDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ClipUploadUrlResponseDto> {
    return this.monitoringService.createClipUploadUrl(
      examSessionId,
      user.id,
      eventId,
      dto.contentType,
    );
  }

  @Post('events/:eventId/clip')
  @ApiOperation({
    summary: '업로드된 영상 클립을 이벤트에 연결',
    description:
      '클립 업로드 URL로 직접 업로드를 마친 뒤, 그 경로를 해당 부정행위 이벤트 로그에 연결한다.',
  })
  @ApiStandardResponse(ProctoringEventResponseDto, { status: 201, message: 'Clip attached' })
  async attachClip(
    @Param('examSessionId') examSessionId: string,
    @Param('eventId') eventId: string,
    @Body() dto: AttachClipDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ProctoringEventResponseDto> {
    const event = await this.monitoringService.attachClip(
      examSessionId,
      user.id,
      eventId,
      dto.clipPath,
    );
    return toEventDto(event);
  }
}
