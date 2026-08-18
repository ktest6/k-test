import { Inject, Injectable, Logger } from '@nestjs/common';
import { OnEvent } from '@nestjs/event-emitter';
import {
  QUESTION_GENERATOR,
  QuestionGeneratorPort,
} from '../../../ai/domain/ports/question-generator.port';
import { describeError } from '../../../../common/utils/describe-error.util';
import { QuestionService } from '../../../question/application/services/question.service';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';
import {
  DOCUMENT_REPOSITORY,
  DocumentRepository,
} from '../../domain/document.repository.interface';
import {
  DOCUMENT_UPLOADED_EVENT,
  DocumentUploadedEvent,
} from '../../domain/events/document-uploaded.event';

/**
 * document.uploaded 이벤트를 받아 AI(QuestionGeneratorPort)로 문항 초안을
 * 만들고 question 모듈에 저장한다. document 모듈은 question 모듈을 직접
 * 호출하지 않고 이 리스너에서만 QuestionService(Repository 인터페이스를
 * 감싼 얇은 서비스)를 주입받아 쓴다 — verifications → submission 간
 * 이벤트 결합과 같은 패턴.
 */
@Injectable()
export class DocumentUploadedListener {
  private readonly logger = new Logger(DocumentUploadedListener.name);

  constructor(
    @Inject(DOCUMENT_REPOSITORY) private readonly documentRepository: DocumentRepository,
    @Inject(QUESTION_GENERATOR) private readonly questionGenerator: QuestionGeneratorPort,
    private readonly questionService: QuestionService,
  ) {}

  @OnEvent(DOCUMENT_UPLOADED_EVENT)
  async handle(event: DocumentUploadedEvent): Promise<void> {
    try {
      await this.documentRepository.markProcessing(event.documentId);

      const generated = await this.questionGenerator.generate({
        documentId: event.documentId,
        filePath: event.filePath,
        fileName: event.fileName,
      });

      // TODO: 듣기/말하기 3유형(QuestionSectionType) 콘텐츠를 실제로 생성하도록
      // AI 파이프라인 자체를 다시 설계해야 한다 — 지금 당장은 관리자 페이지가
      // 없어 문항을 SQL로 수동 등록하는 방식으로 가기로 해서, 이 자동 생성
      // 경로는 컴파일만 맞춰두고 손대지 않는다.
      await this.questionService.bulkCreateDrafts(
        event.documentId,
        generated.items.map((item) => ({
          part: item.itemType as QuestionSectionType,
          content: {
            preparationSeconds: 0,
            responseSeconds: 0,
            guideTexts: [],
            instruction: item.prompt,
          },
          checklist: item.checklist.map((c) => ({
            code: c.id,
            description: c.description,
            weight: c.weight,
          })),
        })),
      );

      await this.documentRepository.markCompleted(event.documentId, {
        ...(event.examId ? { examId: event.examId } : {}),
        version: generated.version,
        mode: generated.mode,
        note: generated.note,
      });
    } catch (err) {
      this.logger.error(`문항 생성 실패 (documentId=${event.documentId}): ${describeError(err)}`);
      const message = err instanceof Error ? err.message : '문항 생성에 실패했습니다.';
      await this.documentRepository.markFailed(event.documentId, message);
    }
  }
}
