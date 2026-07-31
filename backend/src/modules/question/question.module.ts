import { Module } from '@nestjs/common';
import { QUESTION_REPOSITORY } from './domain/question.repository.interface';
import { QuestionService } from './application/services/question.service';
import { SupabaseQuestionRepository } from './infrastructure/repositories/supabase-question.repository';

@Module({
  providers: [
    QuestionService,
    { provide: QUESTION_REPOSITORY, useClass: SupabaseQuestionRepository },
  ],
  exports: [QuestionService],
})
export class QuestionModule {}
