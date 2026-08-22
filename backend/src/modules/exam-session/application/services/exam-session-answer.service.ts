import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  ConflictDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { describeError } from '../../../../common/utils/describe-error.util';
import {
  SignedUploadUrl,
  StorageUploadUrlService,
} from '../../../../infrastructure/supabase/storage-upload-url.service';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import {
  SKIPPED_QUESTION_REPOSITORY,
  SkippedQuestionRepository,
} from '../../domain/skipped-question.repository.interface';
import { ExamSessionQuestionService } from './exam-session-question.service';
import { ExamSessionReportService } from './exam-session-report.service';
import { ExamSessionService } from './exam-session.service';

const ANSWER_AUDIO_BUCKET = 'answer-audio';

const AUDIO_EXTENSION_BY_CONTENT_TYPE: Record<string, string> = {
  'audio/webm': 'webm',
  'audio/wav': 'wav',
  'audio/x-wav': 'wav',
  'audio/mpeg': 'mp3',
  'audio/mp4': 'm4a',
  'audio/ogg': 'ogg',
};

export interface SaveAnswerInput {
  audioFileUrl: string;
  durationMs?: number;
}

export interface AnswerWithScoreResult {
  answer: Answer;
  graded: boolean;
  score: Record<string, unknown> | null;
}

@Injectable()
export class ExamSessionAnswerService {
  private readonly logger = new Logger(ExamSessionAnswerService.name);

  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly answerService: AnswerService,
    private readonly scoringService: ScoringService,
    private readonly storageUploadUrlService: StorageUploadUrlService,
    @Inject(SKIPPED_QUESTION_REPOSITORY)
    private readonly skippedQuestionRepository: SkippedQuestionRepository,
    private readonly examSessionReportService: ExamSessionReportService,
  ) {}

  async save(
    examSessionId: string,
    questionId: string,
    userId: string,
    input: SaveAnswerInput,
  ): Promise<AnswerWithScoreResult> {
    await this.examSessionService.assertActiveSession(examSessionId, userId);
    await this.examSessionQuestionService.getQuestion(examSessionId, questionId, userId);

    const answer = await this.answerService.save(
      {
        examSessionId,
        questionId,
        type: AnswerType.AUDIO,
        contentText: null,
        audioFileUrl: input.audioFileUrl,
      },
      input.durationMs ?? null,
    );

    // 건너뛴 문항에 마음을 바꿔 답을 저장하는 경우 — 스킵 기록을 지워서
    // "답했는데 건너뛴 것으로도 잡히는" 이중 상태를 막는다.
    await this.skippedQuestionRepository.deleteBySessionAndQuestion(examSessionId, questionId);

    await this.checkAndFinalizeQuietly(examSessionId, userId);

    return this.withScore(answer);
  }

  /**
   * 문항을 답하지 않고 건너뛴다. 답안이 없으므로 채점 파이프라인과는 접점이
   * 없다 — "이 문항은 처리됐다(답했거나 건너뛰었거나)"만 기록해서, 나중에
   * 마지막 문항까지 처리됐는지 판정(최종 리포트 제출 트리거)에 쓴다. 이미
   * 답안이 저장된 문항은 건너뛸 수 없다 — 되돌리려면 신청 취소가 아니라
   * 관리자 개입이 필요한 수준의 예외 상황으로 본다.
   */
  async skip(examSessionId: string, questionId: string, userId: string): Promise<void> {
    await this.examSessionService.assertActiveSession(examSessionId, userId);
    const { answered } = await this.examSessionQuestionService.getQuestion(
      examSessionId,
      questionId,
      userId,
    );
    if (answered) {
      throw new ConflictDomainException('이미 답안을 저장한 문항은 건너뛸 수 없습니다.');
    }

    await this.skippedQuestionRepository.create(examSessionId, questionId);

    await this.checkAndFinalizeQuietly(examSessionId, userId);
  }

  async get(
    examSessionId: string,
    questionId: string,
    userId: string,
  ): Promise<AnswerWithScoreResult> {
    // 세션이 끝난 뒤에도(제출/만료) 자기 답안은 읽을 수 있어야 하므로 소유권/문항 소속만 확인한다.
    await this.examSessionQuestionService.getQuestion(examSessionId, questionId, userId);

    const answer = await this.answerService.findBySessionAndQuestion(examSessionId, questionId);
    if (!answer) {
      throw new NotFoundDomainException('아직 저장된 답안이 없습니다.');
    }

    return this.withScore(answer);
  }

  /** 답안 음성 파일을 올릴 signed URL 발급. 경로는 서버가 정해서 발급 단계부터 바꿔치기를 막는다. */
  async createUploadUrl(
    examSessionId: string,
    questionId: string,
    userId: string,
    contentType: string,
  ): Promise<SignedUploadUrl> {
    await this.examSessionService.assertActiveSession(examSessionId, userId);
    await this.examSessionQuestionService.getQuestion(examSessionId, questionId, userId);

    const extension = AUDIO_EXTENSION_BY_CONTENT_TYPE[contentType];
    const path = `${userId}/${examSessionId}/${questionId}.${extension}`;

    return this.storageUploadUrlService.createSignedUploadUrl(ANSWER_AUDIO_BUCKET, path, {
      upsert: true,
    });
  }

  private async withScore(answer: Answer): Promise<AnswerWithScoreResult> {
    const score = await this.scoringService.findByAnswerId(answer.id);
    return { answer, graded: score !== null, score: score?.rawResponse ?? null };
  }

  /**
   * 이미 끝난 답안 저장/스킵 처리를 되돌릴 이유가 없으므로, 최종 리포트 제출
   * 실패(assessment 장애 등)는 이 호출의 응답에 영향을 주지 않고 로그만 남긴다.
   */
  private async checkAndFinalizeQuietly(examSessionId: string, userId: string): Promise<void> {
    try {
      await this.examSessionReportService.checkAndFinalize(examSessionId, userId);
    } catch (err) {
      this.logger.error(
        `최종 리포트 제출 실패 (examSessionId=${examSessionId}): ${describeError(err)}`,
      );
    }
  }
}
