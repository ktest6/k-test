import { ExecutionContext, UnauthorizedException } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { Reflector } from '@nestjs/core';
import { JwtService } from '@nestjs/jwt';
import { appConfig } from '../../config/configuration';
import { Role } from '../enums/role.enum';
import { JwtAuthGuard } from './jwt-auth.guard';

function buildContext(headers: Record<string, string> = {}): {
  context: ExecutionContext;
  request: { headers: Record<string, string>; user?: unknown };
} {
  const request: { headers: Record<string, string>; user?: unknown } = { headers };
  const context = {
    getHandler: () => ({}),
    getClass: () => ({}),
    switchToHttp: () => ({ getRequest: () => request }),
  } as unknown as ExecutionContext;
  return { context, request };
}

function buildGuard(
  overrides: Partial<{ getAllAndOverride: jest.Mock; verifyAsync: jest.Mock }> = {},
) {
  const getAllAndOverride = overrides.getAllAndOverride ?? jest.fn().mockReturnValue(false);
  const verifyAsync = overrides.verifyAsync ?? jest.fn();
  const reflector = { getAllAndOverride } as unknown as Reflector;
  const jwtService = { verifyAsync } as unknown as JwtService;
  const config = { jwt: { accessSecret: 'secret' } } as unknown as ConfigType<typeof appConfig>;
  return { guard: new JwtAuthGuard(reflector, jwtService, config), verifyAsync, getAllAndOverride };
}

/** isPublic, isOptionalAuth 순서로 반환값을 정한다(getAllAndOverride가 이 순서로 호출됨). */
function metaFlags(isPublic: boolean, isOptionalAuth: boolean) {
  return jest.fn().mockReturnValueOnce(isPublic).mockReturnValueOnce(isOptionalAuth);
}

describe('JwtAuthGuard', () => {
  it('allows a @Public() route without checking for a token', async () => {
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(true, false) });
    const { context } = buildContext();

    await expect(guard.canActivate(context)).resolves.toBe(true);
  });

  it('rejects a normal route with no token', async () => {
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, false) });
    const { context } = buildContext();

    await expect(guard.canActivate(context)).rejects.toThrow(UnauthorizedException);
  });

  it('rejects a normal route with an invalid token', async () => {
    const verifyAsync = jest.fn().mockRejectedValue(new Error('bad token'));
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, false), verifyAsync });
    const { context } = buildContext({ authorization: 'Bearer bad' });

    await expect(guard.canActivate(context)).rejects.toThrow(UnauthorizedException);
  });

  it('attaches request.user on a normal route with a valid token', async () => {
    const verifyAsync = jest
      .fn()
      .mockResolvedValue({ sub: '9', email: 'u@test.com', role: Role.USER });
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, false), verifyAsync });
    const { context, request } = buildContext({ authorization: 'Bearer good' });

    await expect(guard.canActivate(context)).resolves.toBe(true);
    expect(request.user).toEqual({ id: '9', email: 'u@test.com', role: Role.USER });
  });

  it('allows an @OptionalAuth() route with no token, leaving request.user unset', async () => {
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, true) });
    const { context, request } = buildContext();

    await expect(guard.canActivate(context)).resolves.toBe(true);
    expect(request.user).toBeUndefined();
  });

  it('allows an @OptionalAuth() route with an invalid token, leaving request.user unset', async () => {
    const verifyAsync = jest.fn().mockRejectedValue(new Error('bad token'));
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, true), verifyAsync });
    const { context, request } = buildContext({ authorization: 'Bearer bad' });

    await expect(guard.canActivate(context)).resolves.toBe(true);
    expect(request.user).toBeUndefined();
  });

  it('attaches request.user on an @OptionalAuth() route with a valid token', async () => {
    const verifyAsync = jest
      .fn()
      .mockResolvedValue({ sub: '9', email: 'u@test.com', role: Role.USER });
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, true), verifyAsync });
    const { context, request } = buildContext({ authorization: 'Bearer good' });

    await expect(guard.canActivate(context)).resolves.toBe(true);
    expect(request.user).toEqual({ id: '9', email: 'u@test.com', role: Role.USER });
  });

  it('rejects a refresh token on a normal route', async () => {
    const verifyAsync = jest
      .fn()
      .mockResolvedValue({ sub: '9', email: 'u@test.com', role: Role.USER, type: 'refresh' });
    const { guard } = buildGuard({ getAllAndOverride: metaFlags(false, false), verifyAsync });
    const { context } = buildContext({ authorization: 'Bearer refresh' });

    await expect(guard.canActivate(context)).rejects.toThrow(UnauthorizedException);
  });
});
