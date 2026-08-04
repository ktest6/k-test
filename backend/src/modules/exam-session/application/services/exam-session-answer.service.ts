import { Injectable } from '@nestjs/common';
import { NotFoundDomainException } from '../../../../common/exceptions/domain.exception';
import {
  SignedUploadUrl,
  StorageUploadUrlService,
} from '../../../../infrastructure/supabase/storage-upload-url.service';
import { AnswerService } from '../../../answer/application/services/answer.service';
import { Answer } from '../../../answer/domain/entities/answer.entity';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { ScoringService } from '../../../scoring/application/services/scoring.service';
import { ExamSessionQuestionService } from './exam-session-question.service';
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
  type: AnswerType;
  contentText?: string;
  audioFileUrl?: string;
}

export interface AnswerWithScoreResult {
  answer: Answer;
  graded: boolean;
  score: Record<string, unknown> | null;
}

@Injectable()
export class ExamSessionAnswerService {
  constructor(
    private readonly examSessionService: ExamSessionService,
    private readonly examSessionQuestionService: ExamSessionQuestionService,
    private readonly answerService: AnswerService,
    private readonly scoringService: ScoringService,
    private readonly storageUploadUrlService: StorageUploadUrlService,
  ) {}

  async save(
    examSessionId: string,
    questionId: string,
    userId: string,
    input: SaveAnswerInput,
  ): Promise<AnswerWithScoreResult> {
    await this.examSessionService.assertActiveSession(examSessionId, userId);
    await this.examSessionQuestionService.getQuestion(examSessionId, questionId, userId);

    const answer = await this.answerService.save({
      examSessionId,
      questionId,
      type: input.type,
      contentText: input.contentText ?? null,
      audioFileUrl: input.audioFileUrl ?? null,
    });

    return this.withScore(answer);
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
}
