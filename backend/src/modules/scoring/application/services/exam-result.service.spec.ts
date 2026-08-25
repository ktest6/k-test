import { EventEmitter2 } from '@nestjs/event-emitter';
import { ExamResult } from '../../domain/entities/exam-result.entity';
import { EXAM_RESULT_RECORDED_EVENT } from '../../domain/events/exam-result-recorded.event';
import { ExamResultRepository } from '../../domain/exam-result.repository.interface';
import { ExamResultService } from './exam-result.service';

describe('ExamResultService.record', () => {
  it('saves the result and emits exam-result.recorded with the session and user id', async () => {
    const saved = new ExamResult('1', '100', 'B', 70.5, null, null, {}, new Date());
    const record = jest.fn().mockResolvedValue(saved);
    const examResultRepository = { record } as unknown as ExamResultRepository;
    const emit = jest.fn();
    const eventEmitter = { emit } as unknown as EventEmitter2;
    const service = new ExamResultService(examResultRepository, eventEmitter);
    const input = {
      examSessionId: '100',
      finalGrade: 'B',
      percentile: 70.5,
      domainScores: null,
      crossValidationSignals: null,
      rawResponse: {},
    };

    const result = await service.record(input, '9');

    expect(record).toHaveBeenCalledWith(input);
    expect(emit).toHaveBeenCalledWith(
      EXAM_RESULT_RECORDED_EVENT,
      expect.objectContaining({ examSessionId: '100', userId: '9' }),
    );
    expect(result).toBe(saved);
  });
});
