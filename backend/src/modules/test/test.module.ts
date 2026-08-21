import { Module } from '@nestjs/common';
import { TestResetService } from './application/services/test-reset.service';
import { TestController } from './presentation/test.controller';

@Module({
  controllers: [TestController],
  providers: [TestResetService],
})
export class TestModule {}
