import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module';
import { ExamSessionModule } from '../exam-session/exam-session.module';
import { UserModule } from '../user/user.module';
import { TestQuickStartService } from './application/services/test-quick-start.service';
import { TestResetService } from './application/services/test-reset.service';
import { TestController } from './presentation/test.controller';

@Module({
  imports: [AuthModule, UserModule, ExamSessionModule],
  controllers: [TestController],
  providers: [TestResetService, TestQuickStartService],
})
export class TestModule {}
