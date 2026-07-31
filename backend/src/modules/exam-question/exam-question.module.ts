import { Module } from '@nestjs/common';
import { ExamModule } from '../exam/exam.module';
import { QuestionModule } from '../question/question.module';
import { EXAM_QUESTION_REPOSITORY } from './domain/exam-question.repository.interface';
import { ExamQuestionService } from './application/services/exam-question.service';
import { SupabaseExamQuestionRepository } from './infrastructure/repositories/supabase-exam-question.repository';
import { ExamQuestionController } from './presentation/exam-question.controller';

@Module({
  imports: [ExamModule, QuestionModule],
  controllers: [ExamQuestionController],
  providers: [
    ExamQuestionService,
    { provide: EXAM_QUESTION_REPOSITORY, useClass: SupabaseExamQuestionRepository },
  ],
  exports: [ExamQuestionService],
})
export class ExamQuestionModule {}
