import { Body, Controller, Get, Param, Post } from '@nestjs/common';
import { ApiBearerAuth, ApiOperation, ApiTags } from '@nestjs/swagger';
import { ApiCommonErrorResponses } from '../../../common/decorators/api-common-error-responses.decorator';
import { ApiStandardResponse } from '../../../common/decorators/api-standard-response.decorator';
import { CurrentUser } from '../../../common/decorators/current-user.decorator';
import { OptionalAuth } from '../../../common/decorators/optional-auth.decorator';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { StoragePublicUrlService } from '../../../infrastructure/supabase/storage-public-url.service';
import { AnswerResponseDto } from '../application/dto/answer-response.dto';
import { AnswerUploadUrlResponseDto } from '../application/dto/answer-upload-url-response.dto';
import { AvailableExamResponseDto } from '../application/dto/available-exam-response.dto';
import { ExamSessionStatusResponseDto } from '../application/dto/exam-session-status-response.dto';
import { RequestAnswerAudioUploadUrlDto } from '../application/dto/request-answer-audio-upload-url.dto';
import { SaveAnswerDto } from '../application/dto/save-answer.dto';
import { SessionQuestionResponseDto } from '../application/dto/session-question-response.dto';
import { StartExamSessionResponseDto } from '../application/dto/start-exam-session-response.dto';
import {
  AnswerWithScoreResult,
  ExamSessionAnswerService,
} from '../application/services/exam-session-answer.service';
import {
  ExamSessionQuestionService,
  SessionQuestion,
} from '../application/services/exam-session-question.service';
import { ExamSessionService } from '../application/services/exam-session.service';

const QUESTION_ASSETS_BUCKET = 'question-assets';
const ANSWER_AUDIO_BUCKET = 'answer-audio';

@ApiBearerAuth()
@ApiTags('Exam Session')
@ApiCommonErrorResponses()
@Controller()
export class ExamSessionController {
  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly examSessionAnswerService: ExamSessionAnswerService,
    private readonly storagePublicUrlService: StoragePublicUrlService,
  ) {}

  @Get('available-exams')
  @OptionalAuth()
  @ApiOperation({
    summary: '오늘 응시 가능한 시험 목록 조회',
    description:
      '로그인 없이도 호출할 수 있다 — 비로그인이면 지금 신청 가능한(신청 기간 내 + 정원 여유) ' +
      '시험만 내려주고(isApplied는 항상 false), 로그인했으면 신청해서 아직 안 끝난(세션 없음 또는 ' +
      'INPROGRESS) 시험까지 합쳐서 준다. isApplied가 false면 examSessionId/sessionStatus는 항상 ' +
      'null이다 — 프런트는 isApplied로 [신청하기] vs [이어서 풀기]를 구분하면 된다.',
  })
  @ApiStandardResponse(AvailableExamResponseDto, {
    isArray: true,
    message: '오늘 응시 가능한 시험 목록 조회 성공',
  })
  async listAvailable(
    @CurrentUser() user: AuthenticatedUser | undefined,
  ): Promise<AvailableExamResponseDto[]> {
    const availableExams = await this.examSessionService.listAvailable(user?.id ?? null);
    return availableExams.map((item) => ({
      examId: item.exam.id,
      roundName: item.exam.roundName,
      openAt: item.exam.openAt,
      closeAt: item.exam.closeAt,
      applicationOpenAt: item.exam.applicationOpenAt,
      applicationCloseAt: item.exam.applicationCloseAt,
      isApplied: item.isApplied,
      examSessionId: item.session?.id ?? null,
      sessionStatus: item.session?.status ?? null,
    }));
  }

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
      examSessionId: session.id,
      examId: session.examId,
      status: session.status,
      startedAt: session.startedAt,
    };
  }

  @Get('exam-sessions/:examSessionId')
  @ApiOperation({
    summary: '세션 상태 조회',
    description:
      '진행중/제출됨/차단 상태를 반환한다. INPROGRESS가 아니면 더 이상 진행할 수 없다는 뜻이다 — ' +
      '문항별 진행 상황(다음에 풀 문항)은 문항 목록 조회의 answered 필드로 프런트가 직접 계산한다.',
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
    return questions.map((sessionQuestion) => this.toQuestionResponse(sessionQuestion));
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
    const sessionQuestion = await this.examSessionQuestionService.getQuestion(
      examSessionId,
      questionId,
      user.id,
      user.role === Role.ADMIN,
    );
    return this.toQuestionResponse(sessionQuestion);
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

  @Post('exam-sessions/:examSessionId/questions/:questionId/skip')
  @ApiOperation({
    summary: '문항 건너뛰기',
    description:
      '답안 없이 이 문항을 건너뛴다. 이미 답안을 저장한 문항은 건너뛸 수 없다(409). ' +
      '진행중인 세션이 아니면 409. 건너뛴 문항에 나중에 답안을 저장하면 건너뛰기 기록은 자동으로 취소된다.',
  })
  @ApiStandardResponse(SessionQuestionResponseDto, { status: 201, message: '문항 건너뛰기 완료' })
  async skipQuestion(
    @Param('examSessionId') examSessionId: string,
    @Param('questionId') questionId: string,
    @CurrentUser() user: AuthenticatedUser,
  ): Promise<SessionQuestionResponseDto> {
    await this.examSessionAnswerService.skip(examSessionId, questionId, user.id);
    const sessionQuestion = await this.examSessionQuestionService.getQuestion(
      examSessionId,
      questionId,
      user.id,
    );
    return this.toQuestionResponse(sessionQuestion);
  }

  private toQuestionResponse(sessionQuestion: SessionQuestion): SessionQuestionResponseDto {
    const { question, answered, skipped } = sessionQuestion;
    const { content } = question;
    return {
      id: question.id,
      part: question.part,
      answered,
      skipped,
      preparationSeconds: content.preparationSeconds,
      responseSeconds: content.responseSeconds,
      guideTexts: content.guideTexts,
      instruction: content.instruction ?? null,
      imageUrl: content.imageUrl
        ? this.storagePublicUrlService.toPublicUrl(QUESTION_ASSETS_BUCKET, content.imageUrl)
        : null,
      safetyRulesTitle: content.safetyRulesTitle ?? null,
      safetyRules: content.safetyRules ?? null,
      audioUrl: content.audioUrl
        ? this.storagePublicUrlService.toPublicUrl(QUESTION_ASSETS_BUCKET, content.audioUrl)
        : null,
    };
  }

  private toAnswerResponse(result: AnswerWithScoreResult): AnswerResponseDto {
    return {
      id: result.answer.id,
      questionId: result.answer.questionId,
      type: result.answer.type,
      contentText: result.answer.contentText,
      audioFileUrl: result.answer.audioFileUrl
        ? this.storagePublicUrlService.toPublicUrl(ANSWER_AUDIO_BUCKET, result.answer.audioFileUrl)
        : null,
      status: result.answer.status,
      modifiedAt: result.answer.modifiedAt,
      graded: result.graded,
      score: result.score,
    };
  }
}
