import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { SupabaseClient, createClient } from '@supabase/supabase-js';
import WebSocket from 'ws';
import { appConfig } from '../../config/configuration';

type AdminClient = SupabaseClient<any, any, any>;

@Injectable()
export class SupabaseService {
  private readonly adminClient: AdminClient;

  constructor(@Inject(appConfig.KEY) config: ConfigType<typeof appConfig>) {
    this.adminClient = createClient(config.supabase.url, config.supabase.serviceRoleKey, {
      auth: { autoRefreshToken: false, persistSession: false },
      // This backend doesn't use Supabase Realtime, but SupabaseClient
      // constructs a RealtimeClient regardless, which needs a WebSocket
      // constructor. Node's native `WebSocket` isn't guaranteed (stable
      // only from Node 22+), so `ws` is supplied explicitly rather than
      // depending on the runtime's Node version.
      realtime: { transport: WebSocket as unknown as typeof globalThis.WebSocket },
    });
  }

  /**
   * Service-role client. Bypasses RLS — repositories rely on it, so
   * authorization must be enforced in guards/services, not the database.
   */
  getAdminClient(): AdminClient {
    return this.adminClient;
  }
}
