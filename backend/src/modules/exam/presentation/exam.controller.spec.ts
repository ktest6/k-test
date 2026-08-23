import { Exam } from '../domain/entities/exam.entity';
import { ExamService } from '../application/services/exam.service';
import { ExamController } from './exam.controller';

function buildExam(): Exam {
  return new Exam('1', '2026년 1회차', new Date('2026-08-01T00:00:00.000Z'));
}

describe('ExamController.list', () => {
  it('maps each exam to id/roundName/createdAt', async () => {
    const list = jest.fn().mockResolvedValue([buildExam()]);
    const controller = new ExamController({ list } as unknown as ExamService);

    const result = await controller.list();

    expect(result).toEqual([
      { id: '1', roundName: '2026년 1회차', createdAt: new Date('2026-08-01T00:00:00.000Z') },
    ]);
  });
});

describe('ExamController.findById', () => {
  it('delegates to ExamService.findById and maps the response', async () => {
    const findById = jest.fn().mockResolvedValue(buildExam());
    const controller = new ExamController({ findById } as unknown as ExamService);

    const result = await controller.findById('1');

    expect(findById).toHaveBeenCalledWith('1');
    expect(result).toEqual({
      id: '1',
      roundName: '2026년 1회차',
      createdAt: new Date('2026-08-01T00:00:00.000Z'),
    });
  });
});
