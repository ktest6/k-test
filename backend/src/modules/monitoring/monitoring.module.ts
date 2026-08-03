import { Module } from '@nestjs/common';
import { AiModule } from '../ai/ai.module';
import { ExamSessionModule } from '../exam-session/exam-session.module';
import { VerificationsModule } from '../verifications/verifications.module';
import { PROCTORING_EVENT_REPOSITORY } from './domain/proctoring-event.repository.interface';
import { MonitoringService } from './application/services/monitoring.service';
import { SupabaseProctoringEventRepository } from './infrastructure/repositories/supabase-proctoring-event.repository';
import { MonitoringController } from './presentation/monitoring.controller';

@Module({
  imports: [AiModule, ExamSessionModule, VerificationsModule],
  controllers: [MonitoringController],
  providers: [
    MonitoringService,
    { provide: PROCTORING_EVENT_REPOSITORY, useClass: SupabaseProctoringEventRepository },
  ],
})
export class MonitoringModule {}
