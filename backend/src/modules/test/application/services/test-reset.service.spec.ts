import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';
import { TestResetService } from './test-reset.service';

function buildConfig(overrides: Partial<{ env: string }> = {}): ConfigType<typeof appConfig> {
  return { env: overrides.env ?? 'development' } as ConfigType<typeof appConfig>;
}

function buildSupabaseService(
  rows: { exam_session_id: number }[],
  error: { message: string } | null = null,
) {
  const notMock = jest.fn().mockReturnValue({
    select: jest.fn().mockResolvedValue({ data: rows, error }),
  });
  const updateMock = jest.fn().mockReturnValue({ not: notMock });
  const fromMock = jest.fn().mockReturnValue({ update: updateMock });
  const client = { from: fromMock };
  return {
    service: { getAdminClient: () => client } as unknown as SupabaseService,
    updateMock,
    notMock,
  };
}

describe('TestResetService.resetAllSessionsToInProgress', () => {
  it('rejects in production', async () => {
    const { service: supabaseService } = buildSupabaseService([]);
    const service = new TestResetService(supabaseService, buildConfig({ env: 'production' }));

    await expect(service.resetAllSessionsToInProgress()).rejects.toThrow(ForbiddenDomainException);
  });

  it('resets every session to INPROGRESS and returns the count', async () => {
    const rows = [{ exam_session_id: 1 }, { exam_session_id: 2 }, { exam_session_id: 3 }];
    const { service: supabaseService, updateMock } = buildSupabaseService(rows);
    const service = new TestResetService(supabaseService, buildConfig());

    const count = await service.resetAllSessionsToInProgress();

    expect(updateMock).toHaveBeenCalledWith({
      status: SessionStatus.INPROGRESS,
      resume_count: 0,
    });
    expect(count).toBe(3);
  });

  it('throws when the update fails', async () => {
    const { service: supabaseService } = buildSupabaseService([], { message: 'db down' });
    const service = new TestResetService(supabaseService, buildConfig());

    await expect(service.resetAllSessionsToInProgress()).rejects.toThrow(ForbiddenDomainException);
  });
});
