import { ExamSession } from '../../../exam-session/domain/entities/exam-session.entity';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';
import { ExamSessionService } from '../../../exam-session/application/services/exam-session.service';
import { GazeCalibrationService } from '../../../verifications/application/services/gaze-calibration.service';
import { IdCardVerificationService } from '../../../verifications/application/services/id-card-verification.service';
import {
  AnalyzeFrameInput,
  AnalyzeFrameResult,
  MonitoringProviderPort,
} from '../../../ai/domain/ports/monitoring-provider.port';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  CreateProctoringEventInput,
  ProctoringEventRepository,
} from '../../domain/proctoring-event.repository.interface';
import { ProctoringEvent } from '../../domain/entities/proctoring-event.entity';
import { MonitoringService } from './monitoring.service';

function buildSession(): ExamSession {
  return new ExamSession(
    '100',
    '7',
    '9',
    SessionStatus.INPROGRESS,
    0,
    new Date('2026-08-04T00:00:00.000Z'),
    null,
    null,
    null,
    new Date(),
  );
}

function buildFrame() {
  return { buffer: Buffer.from('frame'), filename: 'frame.jpg', contentType: 'image/jpeg' };
}

function buildAnalyzedResult(overrides: Partial<AnalyzeFrameResult> = {}): AnalyzeFrameResult {
  return {
    eventSummary: {
      eventDetected: false,
      eventCount: 0,
      severity: 'NORMAL',
      decision: 'NONE',
      createClip: false,
    },
    events: [],
    raw: {},
    ...overrides,
  };
}

function buildService(overrides: {
  examSessionService?: Partial<ExamSessionService>;
  idCardVerificationService?: Partial<IdCardVerificationService>;
  gazeCalibrationService?: Partial<GazeCalibrationService>;
  supabaseService?: Partial<SupabaseService>;
  monitoringProvider?: Partial<MonitoringProviderPort>;
  proctoringEventRepository?: Partial<ProctoringEventRepository>;
}) {
  const examSessionService = {
    assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
    ...overrides.examSessionService,
  } as unknown as ExamSessionService;
  const idCardVerificationService = {
    getVerifiedFacePath: jest.fn().mockResolvedValue(null),
    ...overrides.idCardVerificationService,
  } as unknown as IdCardVerificationService;
  const gazeCalibrationService = {
    getLatestCalibration: jest.fn().mockResolvedValue(null),
    ...overrides.gazeCalibrationService,
  } as unknown as GazeCalibrationService;
  const upload = jest.fn().mockResolvedValue({ data: { path: 'snapshot.jpg' }, error: null });
  const supabaseService = {
    getAdminClient: jest.fn().mockReturnValue({ storage: { from: () => ({ upload }) } }),
    ...overrides.supabaseService,
  } as unknown as SupabaseService;
  const monitoringProvider = {
    analyze: jest.fn().mockResolvedValue(buildAnalyzedResult()),
    calibrate: jest.fn(),
    ...overrides.monitoringProvider,
  };
  const proctoringEventRepository = {
    create: jest.fn(),
    findByExamSessionId: jest.fn(),
    ...overrides.proctoringEventRepository,
  };

  return new MonitoringService(
    examSessionService,
    idCardVerificationService,
    gazeCalibrationService,
    supabaseService,
    monitoringProvider,
    proctoringEventRepository,
  );
}

describe('MonitoringService.analyze', () => {
  it('gates on assertActiveSession before calling the provider', async () => {
    const assertActiveSession = jest.fn().mockResolvedValue(buildSession());
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult());
    const service = buildService({
      examSessionService: { assertActiveSession },
      monitoringProvider: { analyze },
    });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(assertActiveSession).toHaveBeenCalledWith('100', '9');
    expect(analyze).toHaveBeenCalledWith(
      expect.objectContaining({ examId: '7', examineeId: '9', runIdentityCheck: false }),
    );
  });

  it('does not record anything when no event is detected', async () => {
    const create = jest.fn();
    const service = buildService({ proctoringEventRepository: { create } });

    const result = await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(create).not.toHaveBeenCalled();
    expect(result.recordedEvents).toEqual([]);
    expect(result.severity).toBe('NORMAL');
  });

  it('records each detected event with the batch severity and the uploaded snapshot path', async () => {
    const savedEvent = new ProctoringEvent(
      '1',
      '100',
      'FACE_OUT_OF_FRAME',
      'MEDIUM',
      { face_count: 0 },
      new Date(),
      'proctoring/snapshot.jpg',
    );
    const create = jest
      .fn<Promise<ProctoringEvent>, [CreateProctoringEventInput]>()
      .mockResolvedValue(savedEvent);
    const analyze = jest.fn().mockResolvedValue(
      buildAnalyzedResult({
        eventSummary: {
          eventDetected: true,
          eventCount: 1,
          severity: 'MEDIUM',
          decision: 'RECORD_EVENT',
          createClip: false,
        },
        events: [{ eventType: 'FACE_OUT_OF_FRAME', details: { face_count: 0 } }],
      }),
    );
    const service = buildService({
      monitoringProvider: { analyze },
      proctoringEventRepository: { create },
    });

    const result = await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    const createInput = create.mock.calls[0][0];
    expect(createInput.examSessionId).toBe('100');
    expect(createInput.eventType).toBe('FACE_OUT_OF_FRAME');
    expect(createInput.severity).toBe('MEDIUM');
    expect(createInput.meta).toEqual({ face_count: 0 });
    expect(createInput.snapshotPath).toMatch(/^100\/\d+-.+\.jpg$/);
    expect(result.recordedEvents).toEqual([savedEvent]);
    expect(result.severity).toBe('MEDIUM');
  });

  it('records the event with a null snapshot path when the snapshot upload fails', async () => {
    const savedEvent = new ProctoringEvent(
      '1',
      '100',
      'FACE_OUT_OF_FRAME',
      'MEDIUM',
      { face_count: 0 },
      new Date(),
      null,
    );
    const create = jest.fn().mockResolvedValue(savedEvent);
    const analyze = jest.fn().mockResolvedValue(
      buildAnalyzedResult({
        eventSummary: {
          eventDetected: true,
          eventCount: 1,
          severity: 'MEDIUM',
          decision: 'RECORD_EVENT',
          createClip: false,
        },
        events: [{ eventType: 'FACE_OUT_OF_FRAME', details: { face_count: 0 } }],
      }),
    );
    const upload = jest.fn().mockResolvedValue({ data: null, error: { message: 'boom' } });
    const getAdminClient = jest.fn().mockReturnValue({ storage: { from: () => ({ upload }) } });
    const service = buildService({
      monitoringProvider: { analyze },
      proctoringEventRepository: { create },
      supabaseService: { getAdminClient },
    });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ eventType: 'FACE_OUT_OF_FRAME', snapshotPath: null }),
    );
  });

  it('returns a neutral result and does not throw when the provider call fails', async () => {
    const analyze = jest.fn().mockRejectedValue(new Error('monitoring unreachable'));
    const create = jest.fn();
    const service = buildService({
      monitoringProvider: { analyze },
      proctoringEventRepository: { create },
    });

    const result = await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(result).toEqual({
      severity: 'NORMAL',
      decision: 'NONE',
      createClip: false,
      eventCount: 0,
      recordedEvents: [],
    });
    expect(create).not.toHaveBeenCalled();
  });

  it('fetches and attaches the verified face image when runIdentityCheck is requested', async () => {
    const getVerifiedFacePath = jest.fn().mockResolvedValue('9/7/face.jpg');
    const download = jest.fn().mockResolvedValue({
      data: { arrayBuffer: () => Promise.resolve(Buffer.from('ref')), type: 'image/jpeg' },
      error: null,
    });
    const getAdminClient = jest.fn().mockReturnValue({ storage: { from: () => ({ download }) } });
    const analyze = jest
      .fn<Promise<AnalyzeFrameResult>, [AnalyzeFrameInput]>()
      .mockResolvedValue(buildAnalyzedResult());
    const service = buildService({
      idCardVerificationService: { getVerifiedFacePath },
      supabaseService: { getAdminClient },
      monitoringProvider: { analyze },
    });

    await service.analyze(
      '100',
      '9',
      {
        capturedAt: '2026-08-04T00:00:00+09:00',
        elapsedMs: 1000,
        captureSequence: 1,
        runIdentityCheck: true,
      },
      buildFrame(),
    );

    expect(getVerifiedFacePath).toHaveBeenCalledWith('7', '9');
    expect(download).toHaveBeenCalledWith('9/7/face.jpg');
    const calledWith = analyze.mock.calls[0][0];
    expect(calledWith.runIdentityCheck).toBe(true);
    expect(calledWith.referenceImage?.filename).toBe('face.jpg');
  });

  it('downgrades runIdentityCheck to false when no verified face image exists', async () => {
    const getVerifiedFacePath = jest.fn().mockResolvedValue(null);
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult());
    const service = buildService({
      idCardVerificationService: { getVerifiedFacePath },
      monitoringProvider: { analyze },
    });

    await service.analyze(
      '100',
      '9',
      {
        capturedAt: '2026-08-04T00:00:00+09:00',
        elapsedMs: 1000,
        captureSequence: 1,
        runIdentityCheck: true,
      },
      buildFrame(),
    );

    expect(analyze).toHaveBeenCalledWith(
      expect.objectContaining({ runIdentityCheck: false, referenceImage: undefined }),
    );
  });

  it('attaches the saved gaze calibration values when one exists', async () => {
    const getLatestCalibration = jest
      .fn()
      .mockResolvedValue({ eyeYawCenter: -2.1937, eyePitchCenter: -20.7994 });
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult());
    const service = buildService({
      gazeCalibrationService: { getLatestCalibration },
      monitoringProvider: { analyze },
    });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(getLatestCalibration).toHaveBeenCalledWith('7', '9');
    expect(analyze).toHaveBeenCalledWith(
      expect.objectContaining({ eyeYawCenter: -2.1937, eyePitchCenter: -20.7994 }),
    );
  });

  it('omits calibration values when none is saved', async () => {
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult());
    const service = buildService({ monitoringProvider: { analyze } });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(analyze).toHaveBeenCalledWith(
      expect.objectContaining({ eyeYawCenter: undefined, eyePitchCenter: undefined }),
    );
  });
});

describe('MonitoringService.getEvents', () => {
  it('delegates to the repository', async () => {
    const findByExamSessionId = jest.fn().mockResolvedValue([]);
    const service = buildService({ proctoringEventRepository: { findByExamSessionId } });

    await service.getEvents('100');

    expect(findByExamSessionId).toHaveBeenCalledWith('100');
  });
});
