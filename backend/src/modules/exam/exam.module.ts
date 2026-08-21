import { Module } from '@nestjs/common';
import { EXAM_SESSION_REPOSITORY } from '../exam-session/domain/exam-session.repository.interface';
import { SupabaseExamSessionRepository } from '../exam-session/infrastructure/repositories/supabase-exam-session.repository';
import { EXAM_APPLICATION_REPOSITORY } from './domain/exam-application.repository.interface';
import { EXAM_REPOSITORY } from './domain/exam.repository.interface';
import { ExamApplicationService } from './application/services/exam-application.service';
import { ExamService } from './application/services/exam.service';
import { SupabaseExamApplicationRepository } from './infrastructure/repositories/supabase-exam-application.repository';
import { SupabaseExamRepository } from './infrastructure/repositories/supabase-exam.repository';
import { AdminExamController } from './presentation/admin-exam.controller';
import { ExamController } from './presentation/exam.controller';

@Module({
  controllers: [ExamController, AdminExamController],
  providers: [
    ExamService,
    ExamApplicationService,
    { provide: EXAM_REPOSITORY, useClass: SupabaseExamRepository },
    { provide: EXAM_APPLICATION_REPOSITORY, useClass: SupabaseExamApplicationRepository },
    // ExamSessionModule이 이미 ExamModule을 가져다 쓰기 때문에(순환 참조 방지),
    // 세션 상태 조회용으로 여기서 리포지토리를 별도로 바인딩한다.
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
  ],
  exports: [ExamService, ExamApplicationService],
})
export class ExamModule {}
