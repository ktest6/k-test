import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  CalibrateGazeInput,
  CalibrateGazeResult,
  MonitoringProviderPort,
} from '../../../ai/domain/ports/monitoring-provider.port';
import { ExamAccessService } from './exam-access.service';
import { GazeCalibrationService } from './gaze-calibration.service';

function buildImage(name: string) {
  return { buffer: Buffer.from(name), filename: `${name}.jpg`, contentType: 'image/jpeg' };
}

function buildResult(overrides: Partial<CalibrateGazeResult> = {}): CalibrateGazeResult {
  return {
    calibrated: true,
    sampleCount: 6,
    eyeYawCenter: -2.1937,
    eyePitchCenter: -20.7994,
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
    order: jest.Mock;
    limit: jest.Mock;
    maybeSingle: jest.Mock;
  } = {
    insert,
    select: jest.fn(),
    eq: jest.fn(),
    order: jest.fn(),
    limit: jest.fn(),
    maybeSingle,
  };
  queryBuilder.select.mockReturnValue(queryBuilder);
  queryBuilder.eq.mockReturnValue(queryBuilder);
  queryBuilder.order.mockReturnValue(queryBuilder);
  queryBuilder.limit.mockReturnValue(queryBuilder);

  return { from: jest.fn().mockReturnValue(queryBuilder) };
}

function buildService(
  overrides: {
    examAccessService?: Partial<ExamAccessService>;
    monitoringProvider?: Partial<MonitoringProviderPort>;
    client?: { insert?: jest.Mock; maybeSingle?: jest.Mock };
  } = {},
) {
  const examAccessService = {
    assertApplied: jest.fn().mockResolvedValue(undefined),
    ...overrides.examAccessService,
  } as unknown as ExamAccessService;
  const monitoringProvider = {
    analyze: jest.fn(),
    calibrate: jest
      .fn<Promise<CalibrateGazeResult>, [CalibrateGazeInput]>()
      .mockResolvedValue(buildResult()),
    ...overrides.monitoringProvider,
  };
  const client = buildClient(overrides.client);
  const supabaseService = {
    getAdminClient: jest.fn().mockReturnValue(client),
  } as unknown as SupabaseService;

  return {
    service: new GazeCalibrationService(supabaseService, examAccessService, monitoringProvider),
    client,
  };
}

describe('GazeCalibrationService.calibrate', () => {
  it('gates on exam application before calling the provider', async () => {
    const assertApplied = jest.fn().mockResolvedValue(undefined);
    const { service } = buildService({ examAccessService: { assertApplied } });

    await service.calibrate('9', '7', [buildImage('center_1')]);

    expect(assertApplied).toHaveBeenCalledWith('9', '7');
  });

  it('propagates a rejection from assertApplied without calling the provider', async () => {
    const assertApplied = jest.fn().mockRejectedValue(new Error('not applied'));
    const calibrate = jest.fn();
    const { service } = buildService({
      examAccessService: { assertApplied },
      monitoringProvider: { calibrate },
    });

    await expect(service.calibrate('9', '7', [buildImage('center_1')])).rejects.toThrow(
      'not applied',
    );
    expect(calibrate).not.toHaveBeenCalled();
  });

  it('passes the images and ids through to the provider and persists a successful result', async () => {
    const calibrate = jest
      .fn<Promise<CalibrateGazeResult>, [CalibrateGazeInput]>()
      .mockResolvedValue(buildResult());
    const insert = jest.fn().mockResolvedValue({ data: null, error: null });
    const { service, client } = buildService({
      monitoringProvider: { calibrate },
      client: { insert },
    });
    const images = [buildImage('center_1'), buildImage('center_2')];

    const result = await service.calibrate('9', '7', images);

    expect(calibrate).toHaveBeenCalledWith({
      examId: '7',
      examineeId: '9',
      calibrationImages: images,
    });
    expect(client.from).toHaveBeenCalledWith('gaze_calibrations');
    expect(insert).toHaveBeenCalledWith(
      expect.objectContaining({
        exam_id: 7,
        user_id: 9,
        eye_yaw_center: -2.1937,
        eye_pitch_center: -20.7994,
        sample_count: 6,
      }),
    );
    expect(result).toEqual(buildResult());
  });

  it('does not persist anything when the provider reports calibrated: false', async () => {
    const calibrate = jest
      .fn<Promise<CalibrateGazeResult>, [CalibrateGazeInput]>()
      .mockResolvedValue(buildResult({ calibrated: false }));
    const insert = jest.fn();
    const { service } = buildService({ monitoringProvider: { calibrate }, client: { insert } });

    await service.calibrate('9', '7', [buildImage('center_1')]);

    expect(insert).not.toHaveBeenCalled();
  });

  it('does not treat a provider failure as a pass — throws instead of silently skipping', async () => {
    const calibrate = jest.fn().mockRejectedValue(new Error('fastapi unreachable'));
    const { service } = buildService({ monitoringProvider: { calibrate } });

    await expect(service.calibrate('9', '7', [buildImage('center_1')])).rejects.toThrow(
      ConflictDomainException,
    );
  });
});

describe('GazeCalibrationService.getLatestCalibration', () => {
  it('returns null when no calibration is on file', async () => {
    const maybeSingle = jest.fn().mockResolvedValue({ data: null });
    const { service } = buildService({ client: { maybeSingle } });

    const result = await service.getLatestCalibration('7', '9');

    expect(result).toBeNull();
  });

  it('maps the stored row to camelCase when a calibration exists', async () => {
    const maybeSingle = jest
      .fn()
      .mockResolvedValue({ data: { eye_yaw_center: -2.1937, eye_pitch_center: -20.7994 } });
    const { service, client } = buildService({ client: { maybeSingle } });

    const result = await service.getLatestCalibration('7', '9');

    expect(client.from).toHaveBeenCalledWith('gaze_calibrations');
    expect(result).toEqual({ eyeYawCenter: -2.1937, eyePitchCenter: -20.7994 });
  });
});
