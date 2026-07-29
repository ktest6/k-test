import { Module } from '@nestjs/common';
import { TEST_REPOSITORY } from './domain/test.repository.interface';
import { TestService } from './application/services/test.service';
import { SupabaseTestRepository } from './infrastructure/repositories/supabase-test.repository';
import { TestController } from './presentation/test.controller';

@Module({
  controllers: [TestController],
  providers: [TestService, { provide: TEST_REPOSITORY, useClass: SupabaseTestRepository }],
  exports: [TestService],
})
export class TestModule {}
