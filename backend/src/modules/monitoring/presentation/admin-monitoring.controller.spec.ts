import { ProctoringEvent } from '../domain/entities/proctoring-event.entity';
import { MonitoringService } from '../application/services/monitoring.service';
import { AdminMonitoringController } from './admin-monitoring.controller';

function buildController(overrides: Partial<{ getEvents: jest.Mock }> = {}) {
  const monitoringService = {
    getEvents: jest.fn(),
    ...overrides,
  } as unknown as MonitoringService;
  return new AdminMonitoringController(monitoringService);
}

describe('AdminMonitoringController.getEvents', () => {
  it('delegates to MonitoringService.getEvents and maps each event', async () => {
    const event = new ProctoringEvent(
      '1',
      '100',
      'PHONE_DETECTED',
      'HIGH',
      { label: 'Mobile Phone' },
      new Date(),
    );
    const getEvents = jest.fn().mockResolvedValue([event]);
    const controller = buildController({ getEvents });

    const result = await controller.getEvents('100');

    expect(getEvents).toHaveBeenCalledWith('100');
    expect(result).toEqual([
      {
        id: '1',
        eventType: 'PHONE_DETECTED',
        severity: 'HIGH',
        meta: { label: 'Mobile Phone' },
        createdAt: event.createdAt,
      },
    ]);
  });
});
