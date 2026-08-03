import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { AnswerResponseDto } from '../application/dto/answer-response.dto';
import { AnswerUploadUrlResponseDto } from '../application/dto/answer-upload-url-response.dto';
import { ExamSessionStatusResponseDto } from '../application/dto/exam-session-status-response.dto';
import { RequestAnswerAudioUploadUrlDto } from '../application/dto/request-answer-audio-upload-url.dto';
import { SaveAnswerDto } from '../application/dto/save-answer.dto';
import { SessionQuestionResponseDto } from '../application/dto/session-question-response.dto';
import { StartExamSessionResponseDto } from '../application/dto/start-exam-session-response.dto';
import {
  AnswerWithScoreResult,
  ExamSessionAnswerService,
} from '../application/services/exam-session-answer.service';
import { ExamSessionQuestionService } from '../application/services/exam-session-question.service';
import { ExamSessionService } from '../application/services/exam-session.service';
import { Question } from '../../question/domain/entities/question.entity';
import { QuestionMode } from '../../question/domain/enums/question-mode.enum';

@ApiBearerAuth()
@ApiTags('Exam Session')
@ApiCommonErrorResponses()
@Controller()
export class ExamSessionController {
  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly examSessionAnswerService: ExamSessionAnswerService,
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
    return questions.map((question) => this.toQuestionResponse(question));
  }

  @Get('exam-sessions/:examSessionId/questions/:questionId')
  @ApiOperation({
    summary: '문항 상세 조회',
    description: '관리자는 세션 소유자가 아니어도 항상 조회할 수 있다.',
  })
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
      user.role === Role.ADMIN,
    );
    return this.toQuestionResponse(question);
  }

  @Post('exam-sessions/:examSessionId/questions/:questionId/answer/upload-url')
  @ApiOperation({
    summary: '답안 음성 업로드용 signed URL 발급',
    description:
      '말하기 답안 녹음 파일을 올릴 URL을 발급한다. 프론트는 이 URL로 Supabase Storage에 직접 업로드한 뒤, ' +
      '응답의 path를 그대로 답안 제출(POST .../answer)의 audioFileUrl로 전달하면 된다.',
  })
  @ApiStandardResponse(AnswerUploadUrlResponseDto, { status: 201, message: '업로드 URL 발급 완료' })
  createAnswerAudioUploadUrl(
    @Param('examSessionId') examSessionId: string,
    @Param('questionId') questionId: string,
    @Body() dto: RequestAnswerAudioUploadUrlDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<AnswerUploadUrlResponseDto> {
    return this.examSessionAnswerService.createUploadUrl(
      examSessionId,
      questionId,
      user.id,
      dto.contentType,
    );
  }

  @Post('exam-sessions/:examSessionId/questions/:questionId/answer')
  @ApiOperation({
    summary: '답안 제출(음성/쓰기)',
    description:
      '문항별 답안을 저장한다. 이미 저장된 답안이 있으면 덮어쓴다. 진행중인 세션이 아니면 409.',
  })
  @ApiStandardResponse(AnswerResponseDto, { status: 201, message: '답안 저장 완료' })
  async saveAnswer(
    @Param('examSessionId') examSessionId: string,
    @Param('questionId') questionId: string,
    @Body() dto: SaveAnswerDto,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<AnswerResponseDto> {
    const result = await this.examSessionAnswerService.save(
      examSessionId,
      questionId,
      user.id,
      dto,
    );
    return this.toAnswerResponse(result);
  }

  @Get('exam-sessions/:examSessionId/questions/:questionId/answer')
  @ApiOperation({ summary: '답안·채점 진행 상태 조회' })
  @ApiStandardResponse(AnswerResponseDto, { message: '답안 조회 성공' })
  async getAnswer(
    @Param('examSessionId') examSessionId: string,
    @Param('questionId') questionId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<AnswerResponseDto> {
    const result = await this.examSessionAnswerService.get(examSessionId, questionId, user.id);
    return this.toAnswerResponse(result);
  }

  private toQuestionResponse(question: Question): SessionQuestionResponseDto {
    return {
      id: question.id,
      part: question.part,
      prompt: question.content.prompt,
      imageUrl: question.content.image_url ?? null,
      mode: (question.content.mode as QuestionMode | undefined) ?? null,
    };
  }

  private toAnswerResponse(result: AnswerWithScoreResult): AnswerResponseDto {
    return {
      id: result.answer.id,
      questionId: result.answer.questionId,
      type: result.answer.type,
      contentText: result.answer.contentText,
      audioFileUrl: result.answer.audioFileUrl,
      status: result.answer.status,
      modifiedAt: result.answer.modifiedAt,
      graded: result.graded,
      score: result.score,
    };
  }
}
