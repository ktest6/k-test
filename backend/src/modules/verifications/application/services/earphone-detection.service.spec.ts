import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  DetectEarphoneInput,
  DetectEarphoneResult,
  EarphoneProviderPort,
} from '../../../ai/domain/ports/earphone-provider.port';
import { ExamAccessService } from './exam-access.service';
import { EarphoneDetectionService } from './earphone-detection.service';

function buildImage() {
  return { buffer: Buffer.from('ear'), filename: 'ear.jpg', contentType: 'image/jpeg' };
}

function buildResult(overrides: Partial<DetectEarphoneResult> = {}): DetectEarphoneResult {
  return {
    earphoneDetected: false,
    leftEarDetected: false,
    rightEarDetected: false,
    leftLabel: null,
    rightLabel: null,
    leftConfidence: 0,
    rightConfidence: 0,
    threshold: 45,
    message: '이어폰이 탐지되지 않았습니다.',
    ...overrides,
  };
}

function buildClient(overrides: { insert?: jest.Mock; maybeSingle?: jest.Mock } = {}) {
  const insert = overrides.insert ?? jest.fn().mockResolvedValue({ data: null, error: null });
  const maybeSingle = overrides.maybeSingle ?? jest.fn().mockResolvedValue({ data: null });

  const queryBuilder: {
    insert: jest.Mock;
    select: jest.Mock;
    eq: jest.Mock;
    limit: jest.Mock;
    maybeSingle: jest.Mock;
  } = {
    insert,
    select: jest.fn(),
    eq: jest.fn(),
    limit: jest.fn(),
    maybeSingle,
  };
  queryBuilder.select.mockReturnValue(queryBuilder);
  queryBuilder.eq.mockReturnValue(queryBuilder);
  queryBuilder.limit.mockReturnValue(queryBuilder);

  return { from: jest.fn().mockReturnValue(queryBuilder) };
}

function buildService(
  overrides: {
    examAccessService?: Partial<ExamAccessService>;
    earphoneProvider?: Partial<EarphoneProviderPort>;
    client?: { insert?: jest.Mock; maybeSingle?: jest.Mock };
  } = {},
) {
  const examAccessService = {
    assertApplied: jest.fn().mockResolvedValue(undefined),
    ...overrides.examAccessService,
  } as unknown as ExamAccessService;
  const earphoneProvider = {
    detect: jest
      .fn<Promise<DetectEarphoneResult>, [DetectEarphoneInput]>()
      .mockResolvedValue(buildResult()),
    ...overrides.earphoneProvider,
  };
  const client = buildClient(overrides.client);
  const supabaseService = {
    getAdminClient: jest.fn().mockReturnValue(client),
  } as unknown as SupabaseService;

  return {
    service: new EarphoneDetectionService(examAccessService, supabaseService, earphoneProvider),
    earphoneProvider,
    client,
  };
}

describe('EarphoneDetectionService.detect', () => {
  it('gates on exam application before calling the provider', async () => {
    const assertApplied = jest.fn().mockResolvedValue(undefined);
    const { service } = buildService({ examAccessService: { assertApplied } });

    await service.detect('9', '7', buildImage(), buildImage());

    expect(assertApplied).toHaveBeenCalledWith('9', '7');
  });

  it('propagates a rejection from assertApplied without calling the provider', async () => {
    const assertApplied = jest.fn().mockRejectedValue(new Error('not applied'));
    const detect = jest.fn();
    const { service } = buildService({
      examAccessService: { assertApplied },
      earphoneProvider: { detect },
    });

    await expect(service.detect('9', '7', buildImage(), buildImage())).rejects.toThrow(
      'not applied',
    );
    expect(detect).not.toHaveBeenCalled();
  });

  it('passes the images and ids through to the provider, persists the result, and returns it as-is', async () => {
    const detect = jest
      .fn<Promise<DetectEarphoneResult>, [DetectEarphoneInput]>()
      .mockResolvedValue(buildResult({ earphoneDetected: true, leftLabel: 'Earbuds' }));
    const insert = jest.fn().mockResolvedValue({ data: null, error: null });
    const { service, client } = buildService({
      earphoneProvider: { detect },
      client: { insert },
    });
    const left = buildImage();
    const right = buildImage();

    const result = await service.detect('9', '7', left, right);

    expect(detect).toHaveBeenCalledWith({
      examId: '7',
      examineeId: '9',
      leftEarImage: left,
      rightEarImage: right,
    });
    expect(client.from).toHaveBeenCalledWith('earphone_logs');
    expect(insert).toHaveBeenCalledWith(
      expect.objectContaining({ exam_id: 7, user_id: 9, earphone_detected: true }),
    );
    expect(result).toEqual(buildResult({ earphoneDetected: true, leftLabel: 'Earbuds' }));
  });

  it('does not treat a provider failure as a pass — throws instead of defaulting to not-detected', async () => {
    const detect = jest.fn().mockRejectedValue(new Error('fastapi unreachable'));
    const insert = jest.fn();
    const { service } = buildService({ earphoneProvider: { detect }, client: { insert } });

    await expect(service.detect('9', '7', buildImage(), buildImage())).rejects.toThrow(
      ConflictDomainException,
    );
    expect(insert).not.toHaveBeenCalled();
  });
});

describe('EarphoneDetectionService.hasPassedCheck', () => {
  it('returns false when no passing check is on file', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: null });
    const { service } = buildService({ client: { maybeSingle } });

    const result = await service.hasPassedCheck('7', '9');

    expect(result).toBe(false);
  });

  it('returns true when a passing check (earphone_detected: false) is on file', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: { id: 'log-1' } });
    const { service, client } = buildService({ client: { maybeSingle } });

    const result = await service.hasPassedCheck('7', '9');

    expect(client.from).toHaveBeenCalledWith('earphone_logs');
    expect(result).toBe(true);
  });
});
