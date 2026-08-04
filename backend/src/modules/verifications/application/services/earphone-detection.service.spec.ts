import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
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

function buildService(
  overrides: {
    examAccessService?: Partial<ExamAccessService>;
    earphoneProvider?: Partial<EarphoneProviderPort>;
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

  return {
    service: new EarphoneDetectionService(examAccessService, earphoneProvider),
    earphoneProvider,
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

  it('passes the images and ids through to the provider and returns the result as-is', async () => {
    const detect = jest
      .fn<Promise<DetectEarphoneResult>, [DetectEarphoneInput]>()
      .mockResolvedValue(buildResult({ earphoneDetected: true, leftLabel: 'Earbuds' }));
    const { service } = buildService({ earphoneProvider: { detect } });
    const left = buildImage();
    const right = buildImage();

    const result = await service.detect('9', '7', left, right);

    expect(detect).toHaveBeenCalledWith({
      examId: '7',
      examineeId: '9',
      leftEarImage: left,
      rightEarImage: right,
    });
    expect(result).toEqual(buildResult({ earphoneDetected: true, leftLabel: 'Earbuds' }));
  });

  it('does not treat a provider failure as a pass — throws instead of defaulting to not-detected', async () => {
    const detect = jest.fn().mockRejectedValue(new Error('fastapi unreachable'));
    const { service } = buildService({ earphoneProvider: { detect } });

    await expect(service.detect('9', '7', buildImage(), buildImage())).rejects.toThrow(
      ConflictDomainException,
    );
  });
});
