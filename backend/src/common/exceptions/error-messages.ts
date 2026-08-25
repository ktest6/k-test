/**
 * Shared English message builders for domain exceptions and validators.
 * Several exceptions across modules follow the same shape (e.g. "X (id) not
 * found", "failed to communicate with the Y service") — centralizing them
 * here keeps the wording consistent and avoids re-typing the same sentence
 * structure at every throw site.
 */

export function notFound(entity: string, id: string): string {
  return `${entity} (${id}) not found.`;
}

export function notOwnedByUser(noun: string): string {
  return `This ${noun} does not belong to you.`;
}

export function serviceCommunicationFailed(serviceName: string): string {
  return `Failed to communicate with the ${serviceName} service. Please try again later.`;
}

export function operationFailed(action: string): string {
  return `Failed to ${action}.`;
}

export function mustAgreeTo(policy: string): string {
  return `You must agree to the ${policy} to sign up.`;
}

export const EMAIL_ALREADY_IN_USE = 'This email is already in use.';
export const INVALID_CREDENTIALS = 'Invalid email or password.';
export const NOT_AVAILABLE_IN_PRODUCTION = 'This is not available in the production environment.';
