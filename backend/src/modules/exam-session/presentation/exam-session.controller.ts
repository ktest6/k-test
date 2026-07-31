import { Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { ExamSessionStatusResponseDto } from '../application/dto/exam-session-status-response.dto';
import { SessionQuestionResponseDto } from '../application/dto/session-question-response.dto';
import { StartExamSessionResponseDto } from '../application/dto/start-exam-session-response.dto';
import { ExamSessionQuestionService } from '../application/services/exam-session-question.service';
import { ExamSessionService } from '../application/services/exam-session.service';

@ApiBearerAuth()
@ApiTags('Exam Session')
@ApiCommonErrorResponses()
@Controller()
export class ExamSessionController {
  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
  ) {}

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

  @Get('exam-sessions/:examSessionId/questions')
  @ApiOperation({
    summary: '문항 목록 조회',
    description:
      '이 세션이 속한 회차에 배정된 문항을 보여준다. 순서는 세션마다 고정된(새로고침해도 안 바뀌는) 랜덤 순서다. 채점 기준(체크리스트/가중치)은 포함하지 않는다.',
  })
  @ApiStandardResponse(SessionQuestionResponseDto, {
    isArray: true,
    message: '문항 목록 조회 성공',
  })
  async listQuestions(
    @Param('examSessionId') examSessionId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<SessionQuestionResponseDto[]> {
    const questions = await this.examSessionQuestionService.listQuestions(examSessionId, user.id);
    return questions.map((question) => ({
      id: question.id,
      part: question.part,
      prompt: question.content.prompt,
    }));
  }

  @Get('exam-sessions/:examSessionId/questions/:questionId')
  @ApiOperation({ summary: '문항 상세 조회' })
  @ApiStandardResponse(SessionQuestionResponseDto, { message: '문항 조회 성공' })
  async getQuestion(
    @Param('examSessionId') examSessionId: string,
    @Param('questionId') questionId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<SessionQuestionResponseDto> {
    const question = await this.examSessionQuestionService.getQuestion(
      examSessionId,
      questionId,
      user.id,
    );
    return { id: question.id, part: question.part, prompt: question.content.prompt };
  }
}
