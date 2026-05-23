import { useEffect, useMemo, useState } from "react";

export interface DashboardEvent {
  id?: number;
  type: string;
  source?: string;
  level?: "info" | "warning" | "error" | string;
  timestamp?: string;
  payload?: Record<string, unknown>;
}

export interface DashboardHealth {
  cpu_percent?: number | null;
  memory_percent?: number | null;
  process_memory_mb?: number | null;
  llm_tier?: string;
  tools?: Array<{ label: string; value: string }>;
}

export interface VisionFrame {
  source?: string;
  url?: string;
  window_title?: string;
  width?: number;
  height?: number;
  original_width?: number;
  original_height?: number;
  size_kb?: number;
  duration_ms?: number;
  mime_type?: string;
  image_base64?: string;
}

export interface DashboardMission {
  id: string;
  session_id?: string;
  title: string;
  request: string;
  status: "running" | "completed" | "failed" | string;
  created_at?: string;
  updated_at?: string;
  completed_at?: string | null;
  duration_ms?: number | null;
  final_answer?: string | null;
  error?: string | null;
}

const HTTP_URL = window.location.origin;
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/dashboard/ws`;

export function useDashboardEvents() {
  const [events, setEvents] = useState<DashboardEvent[]>([]);
  const [health, setHealth] = useState<DashboardHealth | null>(null);
  const [latestVisionFrame, setLatestVisionFrame] = useState<VisionFrame | null>(null);
  const [missions, setMissions] = useState<DashboardMission[]>([]);
  const [status, setStatus] = useState<"connecting" | "online" | "offline">("connecting");

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let reconnectTimer: number | undefined;

    const fetchSnapshot = async () => {
      try {
        const response = await fetch(`${HTTP_URL}/dashboard/snapshot`);
        if (!response.ok) return;
        const snapshot = await response.json();
        if (cancelled) return;
        setHealth(snapshot.health ?? null);
        setEvents(snapshot.history ?? []);
        setMissions(snapshot.missions ?? []);
      } catch {
        // The WebSocket retry loop owns connection state.
      }
    };

    const connect = () => {
      setStatus("connecting");
      socket = new WebSocket(WS_URL);

      socket.onopen = () => {
        if (!cancelled) setStatus("online");
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as DashboardEvent;
          if (event.type === "dashboard.snapshot") {
            const payload = event.payload as { history?: DashboardEvent[]; health?: DashboardHealth; missions?: DashboardMission[] };
            setHealth(payload.health ?? null);
            setEvents(payload.history ?? []);
            setMissions(payload.missions ?? []);
            return;
          }

          if (event.type === "system.health") {
            setHealth((event.payload as DashboardHealth) ?? null);
          }

          if (event.type === "vision.frame") {
            setLatestVisionFrame((event.payload as VisionFrame) ?? null);
          }

          if (event.type === "mission.started" || event.type === "mission.updated") {
            const mission = (event.payload as { mission?: DashboardMission }).mission;
            if (mission) {
              setMissions((current) => upsertMission(current, mission).slice(0, 10));
            }
          }

          setEvents((current) => [...current, event].slice(-30));
        } catch {
          // Ignore malformed telemetry rather than taking down the dashboard.
        }
      };

      socket.onerror = () => {
        if (!cancelled) setStatus("offline");
      };

      socket.onclose = () => {
        if (cancelled) return;
        setStatus("offline");
        reconnectTimer = window.setTimeout(connect, 2500);
      };
    };

    fetchSnapshot();
    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) window.clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, []);

  const latestEvents = useMemo(() => events.slice(-10).reverse(), [events]);

  return {
    events,
    latestEvents,
    health,
    latestVisionFrame,
    missions,
    status,
    eventCount: events.length,
  };
}

function upsertMission(missions: DashboardMission[], mission: DashboardMission) {
  const existing = missions.filter((item) => item.id !== mission.id);
  return [mission, ...existing].sort((a, b) => {
    const aTime = Date.parse(a.created_at ?? a.updated_at ?? "");
    const bTime = Date.parse(b.created_at ?? b.updated_at ?? "");
    return (Number.isFinite(bTime) ? bTime : 0) - (Number.isFinite(aTime) ? aTime : 0);
  });
}
