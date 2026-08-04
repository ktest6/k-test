alter table identity_logs
  add column document_type text,
  add column raw_response jsonb;
