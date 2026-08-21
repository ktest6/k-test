import { MiddlewareConsumer, Module, NestModule } from '@nestjs/common';
import { ConfigModule, ConfigType } from '@nestjs/config';
import { APP_FILTER, APP_GUARD, APP_INTERCEPTOR } from '@nestjs/core';
import { EventEmitterModule } from '@nestjs/event-emitter';
import { JwtModule, JwtSignOptions } from '@nestjs/jwt';
import { ScheduleModule } from '@nestjs/schedule';
import { appConfig } from './config/configuration';
import { validationSchema } from './config/validation.schema';
import { RolesGuard } from './common/guards/roles.guard';
import { JwtAuthGuard } from './common/guards/jwt-auth.guard';
import { HttpExceptionFilter } from './common/filters/http-exception.filter';
import { TransformResponseInterceptor } from './common/interceptors/transform-response.interceptor';
import { RequestLoggingMiddleware } from './common/middleware/request-logging.middleware';
import { SupabaseModule } from './infrastructure/supabase/supabase.module';
import { HealthModule } from './health/health.module';
import { AuthModule } from './modules/auth/auth.module';
import { UserModule } from './modules/user/user.module';
import { ExamModule } from './modules/exam/exam.module';
import { ExamSessionModule } from './modules/exam-session/exam-session.module';
import { QuestionModule } from './modules/question/question.module';
import { SubmissionModule } from './modules/submission/submission.module';
import { ScoringModule } from './modules/scoring/scoring.module';
import { AiModule } from './modules/ai/ai.module';
import { DocumentModule } from './modules/document/document.module';
import { ExamQuestionModule } from './modules/exam-question/exam-question.module';
import { VerificationsModule } from './modules/verifications/verifications.module';
import { MonitoringModule } from './modules/monitoring/monitoring.module';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true, load: [appConfig], validationSchema }),
    JwtModule.registerAsync({
      global: true,
      inject: [appConfig.KEY],
      useFactory: (config: ConfigType<typeof appConfig>) => ({
        secret: config.jwt.accessSecret,
        signOptions: {
          expiresIn: config.jwt.accessExpiresIn as unknown as JwtSignOptions['expiresIn'],
        },
      }),
    }),
    EventEmitterModule.forRoot(),
    ScheduleModule.forRoot(),
    SupabaseModule,
    HealthModule,
    AuthModule,
    UserModule,
    ExamModule,
    ExamSessionModule,
    VerificationsModule,
    QuestionModule,
    DocumentModule,
    ExamQuestionModule,
    SubmissionModule,
    ScoringModule,
    AiModule,
    MonitoringModule,
  ],
  providers: [
    { provide: APP_GUARD, useClass: JwtAuthGuard },
    { provide: APP_GUARD, useClass: RolesGuard },
    { provide: APP_FILTER, useClass: HttpExceptionFilter },
    { provide: APP_INTERCEPTOR, useClass: TransformResponseInterceptor },
  ],
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    consumer.apply(RequestLoggingMiddleware).forRoutes('*');
  }
}
