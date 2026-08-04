import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import FormData from 'form-data';
import { firstValueFrom } from 'rxjs';
import { appConfig } from '../../../../config/configuration';
import {
  AnalyzeFrameInput,
  AnalyzeFrameResult,
  MonitoringDetectedEvent,
  MonitoringEventSummary,
  MonitoringProviderPort,
} from '../../domain/ports/monitoring-provider.port';

interface RawEventSummary {
  event_detected: boolean;
  event_count: number;
  severity: MonitoringEventSummary['severity'];
  decision: MonitoringEventSummary['decision'];
  create_clip: boolean;
}

interface RawDetectedEvent {
  event_type: string;
  details: Record<string, unknown>;
}

interface RawAnalyzeResponse {
  event_summary: RawEventSummary;
  events: RawDetectedEvent[];
  [key: string]: unknown;
}

/** 도영님 담당 부정행위 감지 서비스의 POST /monitoring/analyze를 호출하는 실제 어댑터. */
@Injectable()
export class MonitoringAdapter implements MonitoringProviderPort {
  constructor(
    private readonly httpService: HttpService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async analyze(input: AnalyzeFrameInput): Promise<AnalyzeFrameResult> {
    const form = new FormData();
    form.append('exam_id', input.examId);
    form.append('examinee_id', input.examineeId);
    form.append('request_id', input.requestId);
    form.append('captured_at', input.capturedAt);
    form.append('elapsed_ms', String(input.elapsedMs));
    form.append('capture_sequence', String(input.captureSequence));
    form.append('run_identity_check', String(input.runIdentityCheck));
    form.append('current_image', input.currentImage.buffer, {
      filename: input.currentImage.filename,
      contentType: input.currentImage.contentType,
    });
    if (input.referenceImage) {
      form.append('reference_image', input.referenceImage.buffer, {
        filename: input.referenceImage.filename,
        contentType: input.referenceImage.contentType,
      });
    }

    const response = await firstValueFrom(
      this.httpService.post<RawAnalyzeResponse>(
        `${this.config.fastApi.url}/monitoring/analyze`,
        form,
        { headers: form.getHeaders() },
      ),
    );

    const raw = response.data;
    const events: MonitoringDetectedEvent[] = (raw.events ?? []).map((e) => ({
      eventType: e.event_type,
      details: e.details,
    }));

    return {
      eventSummary: {
        eventDetected: raw.event_summary.event_detected,
        eventCount: raw.event_summary.event_count,
        severity: raw.event_summary.severity,
        decision: raw.event_summary.decision,
        createClip: raw.event_summary.create_clip,
      },
      events,
      raw: raw as unknown as Record<string, unknown>,
    };
  }
}
