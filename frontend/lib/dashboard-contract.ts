import type { DashboardSnapshot, DashboardStreamEvent, JsonObject } from "@/generated/dashboard-contract";

function record(value: unknown): JsonObject | undefined {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as JsonObject
    : undefined;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function positiveIntegerText(value: unknown): value is string {
  return typeof value === "string" && /^[1-9][0-9]*$/.test(value);
}

export function dashboardSnapshot(value: unknown): DashboardSnapshot | undefined {
  const packet = record(value);
  if (!packet
    || packet.contract_version !== "dashboard_snapshot_v1"
    || packet.schema_version !== "1.0"
    || packet.state !== "READY"
    || !Number.isInteger(packet.snapshot_version)
    || (packet.snapshot_version as number) < 1
    || !finite(packet.generated_at)
    || !Number.isInteger(packet.total)
    || (packet.total as number) < 0
    || !record(packet.candidates)
    || !record(packet.final_ranking)
    || !record(packet.signal_funnel)) return undefined;
  if (Object.keys(packet.candidates as JsonObject).length !== packet.total) return undefined;
  return packet as unknown as DashboardSnapshot;
}

export function dashboardStreamEvent(value: unknown): DashboardStreamEvent | undefined {
  const packet = record(value);
  if (!packet
    || packet.contract_version !== "dashboard_stream_event_v1"
    || !positiveIntegerText(packet.event_id)
    || !["snapshot", "heartbeat"].includes(String(packet.event_type))
    || !Number.isInteger(packet.snapshot_version)
    || (packet.snapshot_version as number) < 0
    || packet.schema_version !== "1.0"
    || !finite(packet.generated_at)
    || !(packet.last_event_id === null || positiveIntegerText(packet.last_event_id))
    || typeof packet.payload_hash !== "string"
    || !/^[0-9a-f]{64}$/.test(packet.payload_hash)
    || typeof packet.replayed !== "boolean"
    || typeof packet.full_snapshot !== "boolean") return undefined;
  if (packet.event_type === "heartbeat") {
    return packet.payload === null ? packet as unknown as DashboardStreamEvent : undefined;
  }
  const payload = dashboardSnapshot(packet.payload);
  if (!payload || payload.snapshot_version !== packet.snapshot_version) return undefined;
  return { ...packet, payload } as unknown as DashboardStreamEvent;
}
