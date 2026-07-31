import { Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { ExamSessionStatusResponseDto } from '../application/dto/exam-session-status-response.dto';
import { StartExamSessionResponseDto } from '../application/dto/start-exam-session-response.dto';
import { ExamSessionService } from '../application/services/exam-session.service';

@ApiBearerAuth()
@ApiTags('Exam Session')
@ApiCommonErrorResponses()
@Controller()
export class ExamSessionController {
  constructor(private readonly examSessionService: ExamSessionService) {}

  @Post('exams/:id/sessions')
  @ApiOperation({
    summary: '시험 시작 (세션 생성)',
    description:
      '신청하지 않았거나 응시 기간이 아니면 409/403. 중단됐던 진행중 세션이 있으면 새로 만들지 않고 그 세션을 그대로 돌려준다(재개).',
  })
  @ApiStandardResponse(StartExamSessionResponseDto, { status: 201, message: '시험 시작' })
  async start(
    @Param('id') examId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<StartExamSessionResponseDto> {
    const session = await this.examSessionService.start(examId, user.id);
    return {
      id: session.id,
      examId: session.examId,
      status: session.status,
      startedAt: session.startedAt,
    };
  }

  @Get('exam-sessions/:examSessionId')
  @ApiOperation({
    summary: '세션 상태 조회',
    description:
      '진행중/제출됨/만료 상태와 마지막 진입 문항, 남은 시간을 반환한다. 재개 화면 진입 시 이 API로 어디서부터 다시 보여줄지 판단한다.',
  })
  @ApiStandardResponse(ExamSessionStatusResponseDto, { message: '세션 상태 조회 성공' })
  async getStatus(
    @Param('examSessionId') examSessionId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<ExamSessionStatusResponseDto> {
    const result = await this.examSessionService.getStatus(examSessionId, user.id);
    return {
      id: result.session.id,
      examId: result.session.examId,
      status: result.status,
      currentQuestionId: result.session.currentQuestionId,
      remainingSeconds: result.remainingSeconds,
    };
  }
}
