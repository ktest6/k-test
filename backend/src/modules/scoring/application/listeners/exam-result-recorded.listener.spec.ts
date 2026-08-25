import { MailService } from '../../../../infrastructure/mail/mail.service';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
import { ExamResultRecordedEvent } from '../../domain/events/exam-result-recorded.event';
import { ExamResultRecordedListener } from './exam-result-recorded.listener';

function buildUser(overrides: Partial<{ id: string; email: string }> = {}): User {
  return new User(
    overrides.id ?? '9',
    overrides.email ?? 'user@test.com',
    'Gil',
    'Hong',
    'Korea',
    '1990-01-01',
    IdentityDocumentType.PASSPORT,
    'X1234567',
    null,
    new Date(),
    new Date(),
    new Date(),
    0,
    null,
    new Date(),
    new Date(),
    null,
  );
}

describe('ExamResultRecordedListener.handle', () => {
  it('looks up the user and sends the result-ready email', async () => {
    const user = buildUser({ id: '9', email: 'user@test.com' });
    const findById = jest.fn().mockResolvedValue(user);
    const userService = { findById } as unknown as UserService;
    const sendExamResultReady = jest.fn().mockResolvedValue(undefined);
    const mailService = { sendExamResultReady } as unknown as MailService;
    const listener = new ExamResultRecordedListener(userService, mailService);

    await listener.handle(new ExamResultRecordedEvent('100', '9'));

    expect(findById).toHaveBeenCalledWith('9');
    expect(sendExamResultReady).toHaveBeenCalledWith('user@test.com');
  });

  it('does not throw when the user lookup fails', async () => {
    const findById = jest.fn().mockRejectedValue(new Error('user not found'));
    const userService = { findById } as unknown as UserService;
    const sendExamResultReady = jest.fn();
    const mailService = { sendExamResultReady } as unknown as MailService;
    const listener = new ExamResultRecordedListener(userService, mailService);

    await expect(listener.handle(new ExamResultRecordedEvent('100', '9'))).resolves.toBeUndefined();
    expect(sendExamResultReady).not.toHaveBeenCalled();
  });

  it('does not throw when sending the email fails', async () => {
    const user = buildUser();
    const findById = jest.fn().mockResolvedValue(user);
    const userService = { findById } as unknown as UserService;
    const sendExamResultReady = jest.fn().mockRejectedValue(new Error('smtp down'));
    const mailService = { sendExamResultReady } as unknown as MailService;
    const listener = new ExamResultRecordedListener(userService, mailService);

    await expect(listener.handle(new ExamResultRecordedEvent('100', '9'))).resolves.toBeUndefined();
  });
});
