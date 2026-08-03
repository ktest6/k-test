import {
  BadRequestException,
  Body,
  Controller,
  Get,
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
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { ProctoringEvent } from '../domain/entities/proctoring-event.entity';
import { AnalyzeFrameDto } from '../application/dto/analyze-frame.dto';
import { MonitoringAnalyzeResponseDto } from '../application/dto/monitoring-analyze-response.dto';
import { ProctoringEventResponseDto } from '../application/dto/proctoring-event-response.dto';
import { MonitoringService } from '../application/services/monitoring.service';

const MAX_FRAME_SIZE_BYTES = 5 * 1024 * 1024;

function toEventDto(event: ProctoringEvent): ProctoringEventResponseDto {
  return {
    id: event.id,
    eventType: event.eventType,
    severity: event.severity,
    meta: event.meta,
    createdAt: event.createdAt,
  };
}

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
  @ApiStandardResponse(MonitoringAnalyzeResponseDto, { status: 201, message: '프레임 분석 완료' })
  async analyze(
    @Param('examSessionId') examSessionId: string,
    @UploadedFile() currentImage: Express.Multer.File,
    @Body() dto: AnalyzeFrameDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<MonitoringAnalyzeResponseDto> {
    if (!currentImage) {
      throw new BadRequestException('current_image 파일이 필요합니다.');
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

  @Get('events')
  @Roles(Role.ADMIN)
  @ApiOperation({ summary: '세션의 부정행위 이벤트 목록 조회 (관리자)' })
  @ApiStandardResponse(ProctoringEventResponseDto, {
    isArray: true,
    message: '모니터링 이벤트 조회 성공',
  })
  async getEvents(
    @Param('examSessionId') examSessionId: string,
  ): Promise<ProctoringEventResponseDto[]> {
    const events = await this.monitoringService.getEvents(examSessionId);
    return events.map(toEventDto);
  }
}
