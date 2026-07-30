import { CallHandler, ExecutionContext } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { of } from 'rxjs';
import { ApiResponse } from '../interfaces/api-response.interface';
import { TransformResponseInterceptor } from './transform-response.interceptor';

function buildContext(statusCode: number, url = '/test'): ExecutionContext {
  const response = { statusCode };
  const request = { url };
  return {
    switchToHttp: () => ({
      getResponse: () => response,
      getRequest: () => request,
    }),
    getHandler: () => jest.fn(),
  } as unknown as ExecutionContext;
}

function buildHandler(payload: unknown): CallHandler {
  return { handle: () => of(payload) };
}

describe('TransformResponseInterceptor', () => {
  it('wraps a 200 response in the standard success envelope', (done) => {
    const reflector = { get: jest.fn().mockReturnValue(undefined) } as unknown as Reflector;
    const interceptor = new TransformResponseInterceptor(reflector);

    interceptor
      .intercept(buildContext(200, '/users/me'), buildHandler({ id: '1' }))
      .subscribe((result) => {
        const body = result as ApiResponse;
        expect(body.success).toBe(true);
        expect(body.statusCode).toBe(200);
        expect(body.message).toBe('OK');
        expect(body.data).toEqual({ id: '1' });
        expect(body.path).toBe('/users/me');
        expect(typeof body.timestamp).toBe('string');
        done();
      });
  });

  it('defaults data to null when the handler returns nothing', (done) => {
    const reflector = { get: jest.fn().mockReturnValue(undefined) } as unknown as Reflector;
    const interceptor = new TransformResponseInterceptor(reflector);

    interceptor.intercept(buildContext(201), buildHandler(undefined)).subscribe((result) => {
      const body = result as ApiResponse;
      expect(body.data).toBeNull();
      expect(body.message).toBe('Created');
      done();
    });
  });

  it('uses the @ResponseMessage metadata when present', (done) => {
    const reflector = { get: jest.fn().mockReturnValue('로그인 성공') } as unknown as Reflector;
    const interceptor = new TransformResponseInterceptor(reflector);

    interceptor.intercept(buildContext(200), buildHandler({})).subscribe((result) => {
      expect((result as ApiResponse).message).toBe('로그인 성공');
      done();
    });
  });

  it('passes 204 responses through untouched (no envelope, no body)', (done) => {
    const reflector = { get: jest.fn() } as unknown as Reflector;
    const interceptor = new TransformResponseInterceptor(reflector);

    interceptor.intercept(buildContext(204), buildHandler(undefined)).subscribe((result) => {
      expect(result).toBeUndefined();
      done();
    });
  });
});
