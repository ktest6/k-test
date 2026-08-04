import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import {
  ANSWER_SAVED_EVENT,
  AnswerSavedEvent,
} from '../../../answer/domain/events/answer-saved.event';
import { AnswerType } from '../../../answer/domain/enums/answer-type.enum';
import { QuestionService } from '../../../question/application/services/question.service';
import {
  SCORING_PROVIDER,
  ScoringProviderPort,
} from '../../../ai/domain/ports/scoring-provider.port';
import { ScoringService } from '../services/scoring.service';

/**
 * 답안이 저장될 때마다(answer.saved) 문항 정보(프롬프트/체크리스트)를 곁들여
 * assessment 서비스에 채점을 요청하고, 결과를 tb_score에 저장한다. scoring
 * 모듈은 answer 모듈을 직접 호출하지 않고 이 이벤트만 구독한다(document →
 * question 생성과 같은 패턴). 재저장(upsert)마다 다시 채점된다.
 *
 * 채점 요청이 실패해도(assessment 미배포/타임아웃/그 문항 audio 무음 등) 답안
 * 저장 자체는 이미 끝난 뒤라 응시자 화면에는 영향 없다 — graded는 그대로
 * false로 남고, 나중에 다시 저장하면 재시도된다.
 */
@Injectable()
export class AnswerSavedListener {
  private readonly logger = new Logger(AnswerSavedListener.name);

  constructor(
    private readonly questionService: QuestionService,
    private readonly scoringService: ScoringService,
    @Inject(SCORING_PROVIDER) private readonly scoringProvider: ScoringProviderPort,
  ) {}

  @OnEvent(ANSWER_SAVED_EVENT)
  async handle(event: AnswerSavedEvent): Promise<void> {
    try {
      const question = await this.questionService.findById(event.questionId);

      const rawResponse = await this.scoringProvider.score({
        answerId: event.answerId,
        answerType: event.type === AnswerType.AUDIO ? 'AUDIO' : 'TEXT',
        contentText: event.contentText,
        audioFileUrl: event.audioFileUrl,
        durationMs: event.durationMs,
        item: {
          itemId: question.content.item_id,
          prompt: question.content.prompt,
          expectedRegister: question.content.expected_register,
          checklist: question.checklistItems.map((c) => ({
            id: c.code,
            description: c.description,
            weight: c.weight,
          })),
        },
      });

      await this.scoringService.record({ answerId: event.answerId, rawResponse });
    } catch (err) {
      this.logger.error(`채점 요청 실패 (answerId=${event.answerId})`, err);
    }
  }
}
