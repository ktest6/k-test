import { Inject, Injectable } from '@nestjs/common';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { ExamResult } from '../../domain/entities/exam-result.entity';
import {
  EXAM_RESULT_RECORDED_EVENT,
  ExamResultRecordedEvent,
} from '../../domain/events/exam-result-recorded.event';
import {
  EXAM_RESULT_REPOSITORY,
  ExamResultRepository,
  RecordExamResultInput,
} from '../../domain/exam-result.repository.interface';

@Injectable()
export class ExamResultService {
  constructor(
    @Inject(EXAM_RESULT_REPOSITORY) private readonly examResultRepository: ExamResultRepository,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  async record(input: RecordExamResultInput, userId: string): Promise<ExamResult> {
    const result = await this.examResultRepository.record(input);

    this.eventEmitter.emit(
      EXAM_RESULT_RECORDED_EVENT,
      new ExamResultRecordedEvent(input.examSessionId, userId),
    );

    return result;
  }

  findById(id: string): Promise<ExamResult | null> {
    return this.examResultRepository.findById(id);
  }

  findByExamSessionId(examSessionId: string): Promise<ExamResult | null> {
    return this.examResultRepository.findByExamSessionId(examSessionId);
  }

  listExamSessionIdsWithResult(): Promise<string[]> {
    return this.examResultRepository.listExamSessionIdsWithResult();
  }
}
