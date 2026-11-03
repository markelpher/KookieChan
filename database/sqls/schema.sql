-- Execute no SQL Editor de um projeto Supabase novo.
begin;
create table if not exists bot_config (key text primary key, value jsonb not null);
create table if not exists status_state (
  id text primary key,
  online boolean,
  status_started_at timestamptz,
  accounting_at timestamptz,
  last_check_at timestamptz,
  continuous_online double precision not null default 0 check (continuous_online >= 0),
  continuous_offline double precision not null default 0 check (continuous_offline >= 0),
  total_online double precision not null default 0 check (total_online >= 0),
  total_offline double precision not null default 0 check (total_offline >= 0),
  downtimes_count bigint not null default 0 check (downtimes_count >= 0),
  last_http_code integer,
  last_response_time integer not null default 0 check (last_response_time >= 0),
  status_message_id bigint,
  manual_status_start boolean not null default false
);
alter table status_state add column if not exists manual_status_start boolean not null default false;
create table if not exists status_logs (
  id bigint generated always as identity primary key,
  checked_at timestamptz not null, online boolean not null,
  http_code integer, response_time integer not null
);
create index if not exists status_logs_checked_at_idx on status_logs (checked_at desc);
create table if not exists updates (
  id bigint generated always as identity primary key,
  title text not null unique, description text not null,
  date timestamptz not null, timestamp timestamptz not null default now(),
  delivery_status text not null default 'pending' check (delivery_status in ('pending', 'sent')),
  delivery_attempted_at timestamptz,
  delivery_channel_id bigint,
  delivery_message_id bigint,
  delivered_at timestamptz
);
-- Instalações existentes: anúncios antigos são marcados como enviados para não republicá-los.
alter table updates add column if not exists delivery_status text not null default 'sent' check (delivery_status in ('pending', 'sent'));
alter table updates alter column delivery_status set default 'pending';
alter table updates add column if not exists delivery_attempted_at timestamptz;
alter table updates add column if not exists delivery_channel_id bigint;
alter table updates add column if not exists delivery_message_id bigint;
alter table updates add column if not exists delivered_at timestamptz;
create index if not exists updates_timestamp_idx on updates (timestamp desc);
create index if not exists updates_pending_idx on updates (timestamp, id) where delivery_status = 'pending';
-- Não são criadas políticas para anon/authenticated em uma instalação nova.
-- Políticas preexistentes não são removidas: revise-as no painel do Supabase.
-- A secret key ignora RLS e deve permanecer exclusivamente no servidor.
alter table bot_config enable row level security;
alter table status_state enable row level security;
alter table status_logs enable row level security;
alter table updates enable row level security;
-- A secret key usa service_role. RLS não substitui os privilégios SQL.
grant usage on schema public to service_role;
grant select, insert, update on public.bot_config to service_role;
grant select, insert, update on public.status_state to service_role;
grant select, insert on public.status_logs to service_role;
grant select, insert, update on public.updates to service_role;
grant usage, select on sequence public.status_logs_id_seq to service_role;
grant usage, select on sequence public.updates_id_seq to service_role;

-- Estado e verificação são gravados na mesma transação.
create or replace function record_status_check(p_state jsonb, p_checked_at timestamptz,
  p_online boolean, p_http_code integer, p_response_time integer)
returns void language plpgsql security invoker set search_path = public as $$
begin
  insert into status_logs (checked_at, online, http_code, response_time)
    values (p_checked_at, p_online, p_http_code, p_response_time);
  insert into status_state (id, online, status_started_at, accounting_at, last_check_at,
    continuous_online, continuous_offline, total_online, total_offline,
    downtimes_count, last_http_code, last_response_time, status_message_id, manual_status_start)
  values ('kookie', (p_state->>'online')::boolean,
    (p_state->>'status_started_at')::timestamptz, (p_state->>'accounting_at')::timestamptz,
    (p_state->>'last_check_at')::timestamptz,
    coalesce((p_state->>'continuous_online')::double precision, 0),
    coalesce((p_state->>'continuous_offline')::double precision, 0),
    coalesce((p_state->>'total_online')::double precision, 0),
    coalesce((p_state->>'total_offline')::double precision, 0),
    coalesce((p_state->>'downtimes_count')::bigint, 0),
    (p_state->>'last_http_code')::integer, coalesce((p_state->>'last_response_time')::integer, 0),
    (p_state->>'status_message_id')::bigint,
    coalesce((p_state->>'manual_status_start')::boolean, false))
  on conflict (id) do update set
    online = excluded.online, status_started_at = excluded.status_started_at,
    accounting_at = excluded.accounting_at, last_check_at = excluded.last_check_at,
    continuous_online = excluded.continuous_online, continuous_offline = excluded.continuous_offline,
    total_online = excluded.total_online, total_offline = excluded.total_offline,
    downtimes_count = excluded.downtimes_count, last_http_code = excluded.last_http_code,
    last_response_time = excluded.last_response_time, status_message_id = excluded.status_message_id,
    manual_status_start = excluded.manual_status_start;
end;
$$;
revoke all on function record_status_check(jsonb, timestamptz, boolean, integer, integer) from public, anon, authenticated;
grant execute on function record_status_check(jsonb, timestamptz, boolean, integer, integer) to service_role;
notify pgrst, 'reload schema';
commit;
