import { Controller, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { Roles } from '../../../common/decorators/roles.decorator';
import { Role } from '../../../common/enums/role.enum';
import { ExamSessionStatusResponseDto } from '../application/dto/exam-session-status-response.dto';
import { ExamSessionService } from '../application/services/exam-session.service';

@ApiBearerAuth()
@ApiTags('Admin - Exam Session')
@ApiCommonErrorResponses()
@Roles(Role.ADMIN)
@Controller('exam-sessions/:examSessionId')
export class AdminExamSessionController {
  constructor(private readonly examSessionService: ExamSessionService) {}

  @Post('disqualify')
  @ApiOperation({
    summary: '세션 수동 실격 처리 (관리자)',
    description:
      '모니터링 이벤트를 검토한 관리자가 직접 세션을 실격 처리한다. 이미 제출(SUBMITTED)된 세션은 ' +
      '실격으로 덮어쓸 수 없다. 이미 실격된 세션에 다시 호출해도 안전하다(멱등).',
  })
  @ApiStandardResponse(ExamSessionStatusResponseDto, {
    status: 201,
    message: '세션 실격 처리 완료',
  })
  async disqualify(
    @Param('examSessionId') examSessionId: string,
  ): Promise<ExamSessionStatusResponseDto> {
    const session = await this.examSessionService.disqualify(examSessionId);
    return { id: session.id, examId: session.examId, status: session.status };
  }
}
