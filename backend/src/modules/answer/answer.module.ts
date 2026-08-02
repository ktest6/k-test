import { Module } from '@nestjs/common';
import { ANSWER_REPOSITORY } from './domain/answer.repository.interface';
import { AnswerService } from './application/services/answer.service';
import { SupabaseAnswerRepository } from './infrastructure/repositories/supabase-answer.repository';

@Module({
  providers: [AnswerService, { provide: ANSWER_REPOSITORY, useClass: SupabaseAnswerRepository }],
  exports: [AnswerService],
})
export class AnswerModule {}
