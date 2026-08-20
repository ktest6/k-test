import { BadRequestException } from '@nestjs/common';
import { Role } from '../../../common/enums/role.enum';
import { AuthenticatedUser } from '../../../common/interfaces/authenticated-user.interface';
import { ProctoringEvent } from '../domain/entities/proctoring-event.entity';
import { MonitoringService } from '../application/services/monitoring.service';
import { MonitoringController } from './monitoring.controller';

function buildUser(): AuthenticatedUser {
  return { id: '9', email: 'user@test.com', role: Role.USER };
}

function buildFile(): Express.Multer.File {
  return {
    buffer: Buffer.from('frame'),
    originalname: 'frame.jpg',
    mimetype: 'image/jpeg',
  } as Express.Multer.File;
}

function buildDto() {
  return { capturedAt: '2026-08-04T00:00:00+09:00', elapsedMs: 1000, captureSequence: 1 };
}

function buildController(overrides: Partial<{ analyze: jest.Mock }> = {}) {
  const monitoringService = {
    analyze: jest.fn(),
    ...overrides,
  } as unknown as MonitoringService;
  return new MonitoringController(monitoringService);
}

describe('MonitoringController.analyze', () => {
  it('rejects when no current_image file is attached', async () => {
    const controller = buildController();

    await expect(
      controller.analyze(
        '100',
        undefined as unknown as Express.Multer.File,
        buildDto(),
        buildUser(),
      ),
    ).rejects.toThrow(BadRequestException);
  });

  it('delegates to MonitoringService.analyze and maps the response', async () => {
    const savedEvent = new ProctoringEvent(
      '1',
      '100',
      'FACE_OUT_OF_FRAME',
      'MEDIUM',
      { a: 1 },
      new Date(),
      null,
    );
    const analyze = jest.fn().mockResolvedValue({
      severity: 'MEDIUM',
      decision: 'RECORD_EVENT',
      createClip: false,
      eventCount: 1,
      recordedEvents: [savedEvent],
    });
    const controller = buildController({ analyze });
    const file = buildFile();
    const dto = buildDto();

    const result = await controller.analyze('100', file, dto, buildUser());

    expect(analyze).toHaveBeenCalledWith('100', '9', dto, {
      buffer: file.buffer,
      filename: file.originalname,
      contentType: file.mimetype,
    });
    expect(result).toEqual({
      severity: 'MEDIUM',
      decision: 'RECORD_EVENT',
      createClip: false,
      eventCount: 1,
      recordedEvents: [
        {
          id: '1',
          eventType: 'FACE_OUT_OF_FRAME',
          severity: 'MEDIUM',
          meta: { a: 1 },
          createdAt: savedEvent.createdAt,
          snapshotPath: null,
        },
      ],
    });
  });
});
