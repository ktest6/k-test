import { MailService } from '../../../../infrastructure/mail/mail.service';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';
import { User } from '../../../user/domain/entities/user.entity';
import { UserService } from '../../../user/application/services/user.service';
import { SessionDisqualifiedEvent } from '../../domain/events/session-disqualified.event';
import { SessionDisqualifiedListener } from './session-disqualified.listener';

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

describe('SessionDisqualifiedListener.handle', () => {
  it('looks up the user and sends the disqualification notice email with the reason', async () => {
    const user = buildUser({ id: '9', email: 'user@test.com' });
    const findById = jest.fn().mockResolvedValue(user);
    const userService = { findById } as unknown as UserService;
    const sendDisqualificationNotice = jest.fn().mockResolvedValue(undefined);
    const mailService = { sendDisqualificationNotice } as unknown as MailService;
    const listener = new SessionDisqualifiedListener(userService, mailService);

    const startedAt = new Date('2026-08-22T06:00:00.000Z');
    await listener.handle(new SessionDisqualifiedEvent('100', '9', 'reason text', startedAt));

    expect(findById).toHaveBeenCalledWith('9');
    expect(sendDisqualificationNotice).toHaveBeenCalledWith(
      'user@test.com',
      'reason text',
      startedAt,
    );
  });

  it('does not throw when the user lookup fails', async () => {
    const findById = jest.fn().mockRejectedValue(new Error('user not found'));
    const userService = { findById } as unknown as UserService;
    const sendDisqualificationNotice = jest.fn();
    const mailService = { sendDisqualificationNotice } as unknown as MailService;
    const listener = new SessionDisqualifiedListener(userService, mailService);

    await expect(
      listener.handle(
        new SessionDisqualifiedEvent(
          '100',
          '9',
          'reason text',
          new Date('2026-08-22T06:00:00.000Z'),
        ),
      ),
    ).resolves.toBeUndefined();
    expect(sendDisqualificationNotice).not.toHaveBeenCalled();
  });

  it('does not throw when sending the email fails', async () => {
    const user = buildUser();
    const findById = jest.fn().mockResolvedValue(user);
    const userService = { findById } as unknown as UserService;
    const sendDisqualificationNotice = jest.fn().mockRejectedValue(new Error('smtp down'));
    const mailService = { sendDisqualificationNotice } as unknown as MailService;
    const listener = new SessionDisqualifiedListener(userService, mailService);

    await expect(
      listener.handle(
        new SessionDisqualifiedEvent(
          '100',
          '9',
          'reason text',
          new Date('2026-08-22T06:00:00.000Z'),
        ),
      ),
    ).resolves.toBeUndefined();
  });
});
