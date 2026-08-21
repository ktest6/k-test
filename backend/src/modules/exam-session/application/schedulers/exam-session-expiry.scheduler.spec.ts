import { ExamSessionService } from '../services/exam-session.service';
import { ExamSessionExpiryScheduler } from './exam-session-expiry.scheduler';

describe('ExamSessionExpiryScheduler', () => {
  it('delegates to ExamSessionService.syncAllExpiredSessions', async () => {
    const syncAllExpiredSessions = jest.fn().mockResolvedValue(3);
    const examSessionService = { syncAllExpiredSessions } as unknown as ExamSessionService;
    const scheduler = new ExamSessionExpiryScheduler(examSessionService);

    await scheduler.handleExpiredSessions();

    expect(syncAllExpiredSessions).toHaveBeenCalledTimes(1);
  });
});
