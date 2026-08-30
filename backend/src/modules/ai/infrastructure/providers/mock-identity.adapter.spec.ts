import { MockIdentityAdapter } from './mock-identity.adapter';

describe('MockIdentityAdapter', () => {
  it('always returns a successful match, ignoring the input', async () => {
    const adapter = new MockIdentityAdapter();

    const result = await adapter.verify();

    expect(result.verified).toBe(true);
    expect(result.faceVerified).toBe(true);
    expect(result.applicantVerified).toBe(true);
  });
});
