import { ExamStatus } from './enums/exam-status.enum';
import { computeExamStatus } from './exam-status.util';

describe('computeExamStatus', () => {
  const openAt = new Date('2026-08-01T00:00:00.000Z');
  const closeAt = new Date('2026-08-14T23:59:59.000Z');

  it('returns SCHEDULED before openAt', () => {
    const now = new Date('2026-07-31T23:59:59.000Z');
    expect(computeExamStatus(openAt, closeAt, now)).toBe(ExamStatus.SCHEDULED);
  });

  it('returns OPEN between openAt and closeAt', () => {
    const now = new Date('2026-08-07T12:00:00.000Z');
    expect(computeExamStatus(openAt, closeAt, now)).toBe(ExamStatus.OPEN);
  });

  it('returns OPEN exactly at openAt (inclusive)', () => {
    expect(computeExamStatus(openAt, closeAt, openAt)).toBe(ExamStatus.OPEN);
  });

  it('returns OPEN exactly at closeAt (inclusive)', () => {
    expect(computeExamStatus(openAt, closeAt, closeAt)).toBe(ExamStatus.OPEN);
  });

  it('returns CLOSED after closeAt', () => {
    const now = new Date('2026-08-15T00:00:00.000Z');
    expect(computeExamStatus(openAt, closeAt, now)).toBe(ExamStatus.CLOSED);
  });
});
