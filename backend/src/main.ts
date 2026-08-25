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

/** 로컬 프런트 개발 서버(포트 무관, http만)는 CORS_ORIGIN 설정과 무관하게 항상 허용한다. */
const LOCALHOST_ORIGIN_PATTERN = /^http:\/\/localhost:\d+$/;

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule);
  const configService = app.get(ConfigService);
  const config = configService.getOrThrow<AppConfig>('app');

  app.enableCors({
    origin: (origin, callback) => {
      if (config.corsOrigin === '*') {
        callback(null, true);
        return;
      }
      // 브라우저가 아닌 요청(서버 간 호출, curl, Postman 등)엔 Origin 헤더가 없다 — 막을 이유가 없다.
      if (!origin || LOCALHOST_ORIGIN_PATTERN.test(origin)) {
        callback(null, true);
        return;
      }
      const allowedOrigins = config.corsOrigin.split(',').map((value) => value.trim());
      callback(null, allowedOrigins.includes(origin));
    },
  });
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
