import { ValidationPipe } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { NestFactory } from '@nestjs/core';
import { DocumentBuilder, SwaggerModule } from '@nestjs/swagger';
import { AppModule } from './app.module';
import { AppConfig } from './config/configuration';

/** webpack HMR(hot module replacement) 빌드에서만 주입되는 전역 — 일반 tsc 빌드에는 없다. */
declare const module: {
  hot?: {
    accept(): void;
    dispose(callback: () => void): void;
  };
};

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule);
  const configService = app.get(ConfigService);
  const config = configService.getOrThrow<AppConfig>('app');

  app.enableCors({ origin: config.corsOrigin });
  app.useGlobalPipes(
    new ValidationPipe({ whitelist: true, transform: true, forbidNonWhitelisted: true }),
  );

  if (config.swaggerEnabled) {
    const document = SwaggerModule.createDocument(
      app,
      new DocumentBuilder()
        .setTitle('K-TEST API')
        .setDescription('K-TEST 온라인 시험 플랫폼 백엔드 API')
        .setVersion('0.1.0')
        .addBearerAuth()
        .build(),
    );
    SwaggerModule.setup('docs', app, document);
  }

  await app.listen(config.port);

  if (module.hot) {
    module.hot.accept();
    module.hot.dispose(() => {
      void app.close();
    });
  }
}

void bootstrap();
