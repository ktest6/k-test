import { Controller, Get, Param } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { ProctoringEventResponseDto } from '../application/dto/proctoring-event-response.dto';
import { MonitoringService } from '../application/services/monitoring.service';
import { toEventDto } from './proctoring-event.mapper';

@ApiBearerAuth()
@ApiTags('Admin - Monitoring')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('exam-sessions/:examSessionId/monitoring')
export class AdminMonitoringController {
  constructor(private readonly monitoringService: MonitoringService) {}

  @Get('events')
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
