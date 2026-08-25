import { Module } from '@nestjs/common';
import { EXAM_SESSION_REPOSITORY } from './domain/exam-session.repository.interface';
import { SupabaseExamSessionRepository } from './infrastructure/repositories/supabase-exam-session.repository';
import { ExamSessionAccessService } from './application/services/exam-session-access.service';

/**
 * ExamSessionAccessService(세션 소유권+진행중 여부 확인)만 따로 뗀 얇은 모듈.
 * VerificationsModule과 ExamSessionModule 둘 다 이 서비스가 필요한데,
 * ExamSessionModule은 VerificationsModule에 의존하므로(본인인증/이어폰
 * 서비스를 쓰기 위해) VerificationsModule이 거꾸로 ExamSessionModule을
 * 통째로 가져다 쓰면 순환 참조가 생긴다 — 그래서 리포지토리 바인딩까지
 * 포함해 이 모듈로 분리했다.
 */
@Module({
  providers: [
    ExamSessionAccessService,
    { provide: EXAM_SESSION_REPOSITORY, useClass: SupabaseExamSessionRepository },
  ],
  exports: [ExamSessionAccessService, EXAM_SESSION_REPOSITORY],
})
export class ExamSessionAccessModule {}
