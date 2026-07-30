import { ExamStatus } from './enums/exam-status.enum';
import { computeExamStatus, isApplicationOpen } from './exam-status.util';

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

describe('isApplicationOpen', () => {
  const applicationOpenAt = new Date('2026-07-01T00:00:00.000Z');
  const applicationCloseAt = new Date('2026-07-14T23:59:59.000Z');

  it('returns false before applicationOpenAt', () => {
    const now = new Date('2026-06-30T23:59:59.000Z');
    expect(isApplicationOpen(applicationOpenAt, applicationCloseAt, now)).toBe(false);
  });

  it('returns true between applicationOpenAt and applicationCloseAt', () => {
    const now = new Date('2026-07-07T12:00:00.000Z');
    expect(isApplicationOpen(applicationOpenAt, applicationCloseAt, now)).toBe(true);
  });

  it('returns true exactly at applicationOpenAt (inclusive)', () => {
    expect(isApplicationOpen(applicationOpenAt, applicationCloseAt, applicationOpenAt)).toBe(true);
  });

  it('returns true exactly at applicationCloseAt (inclusive)', () => {
    expect(isApplicationOpen(applicationOpenAt, applicationCloseAt, applicationCloseAt)).toBe(true);
  });

  it('returns false after applicationCloseAt', () => {
    const now = new Date('2026-07-15T00:00:00.000Z');
    expect(isApplicationOpen(applicationOpenAt, applicationCloseAt, now)).toBe(false);
  });
});
