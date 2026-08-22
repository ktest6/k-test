import {
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
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
import { StorageUploadUrlService } from '../../../../infrastructure/supabase/storage-upload-url.service';
import {
  CreateProctoringEventInput,
  ProctoringEventRepository,
} from '../../domain/proctoring-event.repository.interface';
import { ProctoringEvent } from '../../domain/entities/proctoring-event.entity';
import { ClientViolationType } from '../../domain/enums/client-violation-type.enum';
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

/** tb_exam_session.gaze_state 조회/저장 체인까지 포함한 admin client 목 — analyze()가 매번 두 호출을 다 하므로 기본값으로 항상 필요하다. */
function buildAdminClient(
  overrides: {
    upload?: jest.Mock;
    download?: jest.Mock;
    gazeState?: Record<string, unknown> | null;
    updateGazeState?: jest.Mock;
  } = {},
) {
  const upload =
    overrides.upload ??
    jest.fn().mockResolvedValue({ data: { path: 'snapshot.jpg' }, error: null });
  const download = overrides.download ?? jest.fn();
  const maybeSingle = jest
    .fn()
    .mockResolvedValue({ data: { gaze_state: overrides.gazeState ?? null } });
  const selectEq = jest.fn().mockReturnValue({ maybeSingle });
  const select = jest.fn().mockReturnValue({ eq: selectEq });
  const updateEq = overrides.updateGazeState ?? jest.fn().mockResolvedValue({ error: null });
  const update = jest.fn().mockReturnValue({ eq: updateEq });

  return {
    storage: { from: () => ({ upload, download }) },
    from: jest.fn().mockReturnValue({ select, update }),
  };
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
    gazeState: null,
    raw: {},
    ...overrides,
  };
}

function buildService(overrides: {
  examSessionService?: Partial<ExamSessionService>;
  idCardVerificationService?: Partial<IdCardVerificationService>;
  gazeCalibrationService?: Partial<GazeCalibrationService>;
  supabaseService?: Partial<SupabaseService>;
  storageUploadUrlService?: Partial<StorageUploadUrlService>;
  monitoringProvider?: Partial<MonitoringProviderPort>;
  proctoringEventRepository?: Partial<ProctoringEventRepository>;
}) {
  const examSessionService = {
    assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
    getStatus: jest
      .fn()
      .mockResolvedValue({ session: buildSession(), status: SessionStatus.INPROGRESS }),
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
  const supabaseService = {
    getAdminClient: jest.fn().mockReturnValue(buildAdminClient()),
    ...overrides.supabaseService,
  } as unknown as SupabaseService;
  const storageUploadUrlService = {
    createSignedUploadUrl: jest
      .fn()
      .mockResolvedValue({ path: 'clip.webm', signedUrl: 'https://signed', token: 'token' }),
    ...overrides.storageUploadUrlService,
  } as unknown as StorageUploadUrlService;
  const monitoringProvider = {
    analyze: jest.fn().mockResolvedValue(buildAnalyzedResult()),
    calibrate: jest.fn(),
    ...overrides.monitoringProvider,
  };
  const proctoringEventRepository = {
    create: jest.fn(),
    findById: jest.fn(),
    findByExamSessionId: jest.fn().mockResolvedValue([]),
    updateClipPath: jest.fn(),
    ...overrides.proctoringEventRepository,
  };

  return new MonitoringService(
    examSessionService,
    idCardVerificationService,
    gazeCalibrationService,
    supabaseService,
    storageUploadUrlService,
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
      null,
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
    const getAdminClient = jest.fn().mockReturnValue(buildAdminClient({ upload }));
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
    const getAdminClient = jest.fn().mockReturnValue(buildAdminClient({ download }));
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

  it('passes the previously saved gaze state to the provider', async () => {
    const savedState = { consecutive_away_count: 2, last_direction: 'LEFT' };
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult());
    const getAdminClient = jest.fn().mockReturnValue(buildAdminClient({ gazeState: savedState }));
    const service = buildService({
      monitoringProvider: { analyze },
      supabaseService: { getAdminClient },
    });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(analyze).toHaveBeenCalledWith(
      expect.objectContaining({ previousGazeState: savedState }),
    );
  });

  it('omits previousGazeState when none is saved yet', async () => {
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult());
    const service = buildService({ monitoringProvider: { analyze } });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(analyze).toHaveBeenCalledWith(expect.objectContaining({ previousGazeState: undefined }));
  });

  it('saves the gaze state returned by the provider for the next call', async () => {
    const nextState = { consecutive_away_count: 3, last_direction: 'RIGHT' };
    const analyze = jest.fn().mockResolvedValue(buildAnalyzedResult({ gazeState: nextState }));
    const updateGazeState = jest.fn().mockResolvedValue({ error: null });
    const getAdminClient = jest.fn().mockReturnValue(buildAdminClient({ updateGazeState }));
    const service = buildService({
      monitoringProvider: { analyze },
      supabaseService: { getAdminClient },
    });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(updateGazeState).toHaveBeenCalled();
  });

  it('does not touch the saved gaze state when the provider call fails', async () => {
    const analyze = jest.fn().mockRejectedValue(new Error('monitoring unreachable'));
    const updateGazeState = jest.fn();
    const getAdminClient = jest.fn().mockReturnValue(buildAdminClient({ updateGazeState }));
    const service = buildService({
      monitoringProvider: { analyze },
      supabaseService: { getAdminClient },
    });

    await service.analyze(
      '100',
      '9',
      { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 },
      buildFrame(),
    );

    expect(updateGazeState).not.toHaveBeenCalled();
  });
});

function buildEvent(
  overrides: Partial<{ eventType: string; severity: 'LOW' | 'MEDIUM' | 'HIGH' }> = {},
): ProctoringEvent {
  return new ProctoringEvent(
    '1',
    '100',
    overrides.eventType ?? 'TAB_SWITCH',
    overrides.severity ?? 'MEDIUM',
    {},
    new Date(),
    null,
    null,
  );
}

describe('MonitoringService.reportViolation', () => {
  it('gates on assertActiveSession before recording anything', async () => {
    const assertActiveSession = jest.fn().mockRejectedValue(new Error('not active'));
    const create = jest.fn();
    const service = buildService({
      examSessionService: { assertActiveSession },
      proctoringEventRepository: { create },
    });

    await expect(
      service.reportViolation('100', '9', { violationType: ClientViolationType.TAB_SWITCH }),
    ).rejects.toThrow('not active');
    expect(create).not.toHaveBeenCalled();
  });

  it('records a non-dual-monitor violation with its mapped severity and no snapshot', async () => {
    const saved = buildEvent({ eventType: 'PASTE', severity: 'MEDIUM' });
    const create = jest
      .fn<Promise<ProctoringEvent>, [CreateProctoringEventInput]>()
      .mockResolvedValue(saved);
    const disqualify = jest.fn();
    const service = buildService({
      proctoringEventRepository: { create },
      examSessionService: {
        assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
        disqualify,
      },
    });

    const result = await service.reportViolation('100', '9', {
      violationType: ClientViolationType.PASTE,
      meta: { pastedLength: 42 },
    });

    expect(create).toHaveBeenCalledWith({
      examSessionId: '100',
      eventType: 'PASTE',
      severity: 'MEDIUM',
      meta: { pastedLength: 42 },
      snapshotPath: null,
    });
    expect(disqualify).not.toHaveBeenCalled();
    expect(result.event).toBe(saved);
    expect(result.sessionStatus).toBe(SessionStatus.INPROGRESS);
  });

  it('does not auto-disqualify on the first occurrence of a violation type', async () => {
    const create = jest.fn().mockResolvedValue(buildEvent({ eventType: 'DUAL_MONITOR' }));
    const findByExamSessionId = jest
      .fn()
      .mockResolvedValue([buildEvent({ eventType: 'DUAL_MONITOR', severity: 'HIGH' })]);
    const disqualify = jest.fn();
    const service = buildService({
      proctoringEventRepository: { create, findByExamSessionId },
      examSessionService: {
        assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
        disqualify,
      },
    });

    await service.reportViolation('100', '9', { violationType: ClientViolationType.DUAL_MONITOR });

    expect(disqualify).not.toHaveBeenCalled();
  });

  it('auto-disqualifies the session on the 2nd DUAL_MONITOR occurrence and reports the new status', async () => {
    const create = jest.fn().mockResolvedValue(buildEvent({ eventType: 'DUAL_MONITOR' }));
    const findByExamSessionId = jest
      .fn()
      .mockResolvedValue([
        buildEvent({ eventType: 'DUAL_MONITOR', severity: 'HIGH' }),
        buildEvent({ eventType: 'DUAL_MONITOR', severity: 'HIGH' }),
      ]);
    const disqualifiedSession = new ExamSession(
      '100',
      '7',
      '9',
      SessionStatus.DISQUALIFIED,
      0,
      new Date('2026-08-04T00:00:00.000Z'),
      null,
      null,
      null,
      new Date(),
    );
    const disqualify = jest.fn().mockResolvedValue(disqualifiedSession);
    const service = buildService({
      proctoringEventRepository: { create, findByExamSessionId },
      examSessionService: {
        assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
        disqualify,
      },
    });

    const result = await service.reportViolation('100', '9', {
      violationType: ClientViolationType.DUAL_MONITOR,
    });

    expect(disqualify).toHaveBeenCalledWith('100');
    expect(result.sessionStatus).toBe(SessionStatus.DISQUALIFIED);
  });

  it('auto-disqualifies the session on the 2nd occurrence of a non-dual-monitor type too (e.g. TAB_SWITCH)', async () => {
    const create = jest.fn().mockResolvedValue(buildEvent({ eventType: 'TAB_SWITCH' }));
    const findByExamSessionId = jest
      .fn()
      .mockResolvedValue([
        buildEvent({ eventType: 'TAB_SWITCH', severity: 'MEDIUM' }),
        buildEvent({ eventType: 'TAB_SWITCH', severity: 'MEDIUM' }),
      ]);
    const disqualifiedSession = new ExamSession(
      '100',
      '7',
      '9',
      SessionStatus.DISQUALIFIED,
      0,
      new Date('2026-08-04T00:00:00.000Z'),
      null,
      null,
      null,
      new Date(),
    );
    const disqualify = jest.fn().mockResolvedValue(disqualifiedSession);
    const service = buildService({
      proctoringEventRepository: { create, findByExamSessionId },
      examSessionService: {
        assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
        disqualify,
      },
    });

    const result = await service.reportViolation('100', '9', {
      violationType: ClientViolationType.TAB_SWITCH,
    });

    expect(disqualify).toHaveBeenCalledWith('100');
    expect(result.sessionStatus).toBe(SessionStatus.DISQUALIFIED);
  });

  it('does not count other violation types toward this type’s threshold', async () => {
    const create = jest.fn().mockResolvedValue(buildEvent({ eventType: 'DUAL_MONITOR' }));
    const findByExamSessionId = jest
      .fn()
      .mockResolvedValue([
        buildEvent({ eventType: 'DUAL_MONITOR', severity: 'HIGH' }),
        buildEvent({ eventType: 'TAB_SWITCH', severity: 'MEDIUM' }),
        buildEvent({ eventType: 'WINDOW_CLOSE_ATTEMPT', severity: 'HIGH' }),
      ]);
    const disqualify = jest.fn();
    const service = buildService({
      proctoringEventRepository: { create, findByExamSessionId },
      examSessionService: {
        assertActiveSession: jest.fn().mockResolvedValue(buildSession()),
        disqualify,
      },
    });

    await service.reportViolation('100', '9', { violationType: ClientViolationType.DUAL_MONITOR });

    expect(disqualify).not.toHaveBeenCalled();
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

describe('MonitoringService.createClipUploadUrl', () => {
  it('rejects when the caller is not the session owner', async () => {
    const getStatus = jest.fn().mockRejectedValue(new Error('not owner'));
    const service = buildService({ examSessionService: { getStatus } });

    await expect(service.createClipUploadUrl('100', '9', '2', 'video/webm')).rejects.toThrow(
      'not owner',
    );
  });

  it('rejects when the event does not belong to this session', async () => {
    const findById = jest.fn().mockResolvedValue(buildEvent({ eventType: 'DUAL_MONITOR' }));
    const service = buildService({ proctoringEventRepository: { findById } });

    await expect(service.createClipUploadUrl('999', '9', '2', 'video/webm')).rejects.toThrow(
      NotFoundDomainException,
    );
  });

  it('issues a signed upload URL scoped to the user/session/event', async () => {
    const savedEvent = buildEvent({ eventType: 'DUAL_MONITOR' });
    const findById = jest.fn().mockResolvedValue(savedEvent);
    const createSignedUploadUrl = jest
      .fn()
      .mockResolvedValue({ path: '9/100/1.webm', signedUrl: 'https://signed', token: 'token' });
    const service = buildService({
      proctoringEventRepository: { findById },
      storageUploadUrlService: { createSignedUploadUrl },
    });

    const result = await service.createClipUploadUrl('100', '9', '1', 'video/webm');

    expect(createSignedUploadUrl).toHaveBeenCalledWith('proctoring-clips', '9/100/1.webm', {
      upsert: true,
    });
    expect(result).toEqual({ path: '9/100/1.webm', signedUrl: 'https://signed', token: 'token' });
  });
});

describe('MonitoringService.attachClip', () => {
  it('rejects when the clip path does not belong to this user/session', async () => {
    const findById = jest.fn().mockResolvedValue(buildEvent());
    const service = buildService({ proctoringEventRepository: { findById } });

    await expect(service.attachClip('100', '9', '1', 'someone-else/100/1.webm')).rejects.toThrow(
      ForbiddenDomainException,
    );
  });

  it('updates the clip path when everything checks out', async () => {
    const findById = jest.fn().mockResolvedValue(buildEvent());
    const updated = buildEvent();
    const updateClipPath = jest.fn().mockResolvedValue(updated);
    const service = buildService({
      proctoringEventRepository: { findById, updateClipPath },
    });

    const result = await service.attachClip('100', '9', '1', '9/100/1.webm');

    expect(updateClipPath).toHaveBeenCalledWith('1', '9/100/1.webm');
    expect(result).toBe(updated);
  });
});
