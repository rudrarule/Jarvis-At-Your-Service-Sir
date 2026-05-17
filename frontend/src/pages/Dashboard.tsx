import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  ArrowLeft,
  BrainCircuit,
  CheckCircle2,
  CircleDot,
  Command,
  Cpu,
  Eye,
  Gauge,
  Globe2,
  HardDrive,
  Layers3,
  MessageSquareText,
  MousePointer2,
  Pause,
  Play,
  Radar,
  RotateCcw,
  ShieldCheck,
  Square,
  TerminalSquare,
  Zap,
} from "lucide-react";
import { Link } from "react-router-dom";
import ParticleBackground from "@/components/jarvis/ParticleBackground";
import EnhancedChatPanel from "@/components/jarvis/EnhancedChatPanel";
import VoiceButton from "@/components/jarvis/VoiceButton";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import { useJarvis } from "@/hooks/useJarvis";
import { useDashboardEvents, type DashboardEvent, type DashboardMission } from "@/hooks/useDashboardEvents";

type MissionId = string;

interface DisplayMission {
  id: string;
  label: string;
  status: string;
  progress: number;
  detail: string;
}

const demoMissions = [
  {
    id: "retina" as MissionId,
    label: "Retina Watch",
    status: "ACTIVE",
    progress: 72,
    detail: "Screen reasoning and target verification",
  },
  {
    id: "research" as MissionId,
    label: "Research Sweep",
    status: "QUEUED",
    progress: 38,
    detail: "Collect, rank, and summarize web evidence",
  },
  {
    id: "automation" as MissionId,
    label: "Desktop Assist",
    status: "STANDBY",
    progress: 12,
    detail: "Awaiting operator approval for local control",
  },
];

function toDisplayMission(mission: DashboardMission): DisplayMission {
  return {
    id: mission.id,
    label: mission.title || "Untitled mission",
    status: mission.status.toUpperCase(),
    progress: missionProgress(mission.status),
    detail: mission.error || mission.final_answer || mission.request,
  };
}

function missionProgress(status: string) {
  if (status === "completed") return 100;
  if (status === "failed") return 100;
  if (status === "waiting_approval") return 75;
  if (status === "running") return 45;
  return 20;
}

const detections = [
  { label: "Search field", confidence: 98, x: "14%", y: "19%", w: "34%", h: "12%" },
  { label: "Primary action", confidence: 94, x: "61%", y: "27%", w: "24%", h: "14%" },
  { label: "Result cluster", confidence: 91, x: "18%", y: "55%", w: "67%", h: "24%" },
];

const executionNodes = [
  { label: "Observer", state: "complete", detail: "Captured viewport frame" },
  { label: "Retina", state: "complete", detail: "3 actionable regions identified" },
  { label: "Planner", state: "active", detail: "Selecting safest interaction path" },
  { label: "Executor", state: "pending", detail: "Waiting for approved click target" },
  { label: "Verifier", state: "pending", detail: "Will compare post-action state" },
];

const toolStatus = [
  { label: "Browser", value: "CONNECTED", icon: Globe2, tone: "cyan" },
  { label: "Vision", value: "TRACKING", icon: Eye, tone: "emerald" },
  { label: "WhatsApp", value: "READY", icon: MessageSquareText, tone: "cyan" },
  { label: "Memory", value: "CHROMA", icon: HardDrive, tone: "violet" },
  { label: "LLM Tier", value: "BEDROCK", icon: BrainCircuit, tone: "amber" },
  { label: "Guardrail", value: "ARMED", icon: ShieldCheck, tone: "emerald" },
];

function useMissionTelemetry(
  activeMission: MissionId,
  displayMissions: DisplayMission[],
  health: ReturnType<typeof useDashboardEvents>["health"],
  eventCount: number,
) {
  return useMemo(() => {
    const mission = displayMissions.find((item) => item.id === activeMission) ?? displayMissions[0] ?? demoMissions[0];
    return {
      mission,
      vitals: [
        { label: "Confidence", value: `${88 + mission.progress % 11}%`, icon: Gauge },
        { label: "Memory", value: health?.memory_percent == null ? "--" : `${health.memory_percent.toFixed(0)}%`, icon: Zap },
        { label: "CPU", value: health?.cpu_percent == null ? "--" : `${health.cpu_percent.toFixed(0)}%`, icon: Cpu },
        { label: "Events", value: `${eventCount}`, icon: Activity },
      ],
    };
  }, [activeMission, displayMissions, eventCount, health]);
}

export default function Dashboard() {
  const [activeMission, setActiveMission] = useState<MissionId>("retina");
  const [isPaused, setIsPaused] = useState(false);
  const [approvalMode, setApprovalMode] = useState(true);
  const { isListening, isResponding, messages, toggleListening, sendMessage } = useJarvis();
  const dashboard = useDashboardEvents();
  const displayMissions = useMemo(
    () => (dashboard.missions.length ? dashboard.missions.map(toDisplayMission) : demoMissions),
    [dashboard.missions],
  );
  const telemetry = useMissionTelemetry(activeMission, displayMissions, dashboard.health, dashboard.eventCount);
  const retinaImageUrl = dashboard.latestVisionFrame?.image_base64
    ? `data:${dashboard.latestVisionFrame.mime_type ?? "image/jpeg"};base64,${dashboard.latestVisionFrame.image_base64}`
    : null;
  const liveToolStatus = useMemo(() => {
    const backendTools = dashboard.health?.tools ?? [];
    return toolStatus.map((tool) => {
      const live = backendTools.find((item) => item.label === tool.label);
      if (tool.label === "LLM Tier" && dashboard.health?.llm_tier) {
        return { ...tool, value: compactValue(dashboard.health.llm_tier) };
      }
      return live ? { ...tool, value: live.value } : tool;
    });
  }, [dashboard.health]);

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-background text-foreground">
      <ParticleBackground />
      <div className="absolute inset-0 z-[1] scanline pointer-events-none" />
      <div className="absolute inset-0 z-[1] pointer-events-none dashboard-grid" />

      <main className="relative z-10 flex min-h-screen flex-col px-4 py-4 lg:px-6">
        <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <Button asChild variant="ghost" size="icon" className="border border-jarvis-border/40 text-primary hover:bg-primary/10">
              <Link to="/" aria-label="Return to J.A.R.V.I.S interface">
                <ArrowLeft />
              </Link>
            </Button>
            <div>
              <div className="flex items-center gap-3">
                <Radar className="h-5 w-5 text-primary" />
                <h1 className="font-display text-sm tracking-[0.34em] text-primary glow-text md:text-base">
                  J.A.R.V.I.S COMMAND DASHBOARD
                </h1>
              </div>
              <p className="mt-1 font-body text-sm text-jarvis-dim">
                Mission control, Retina telemetry, and live agent operations
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="glass-panel flex items-center gap-2 rounded-md px-3 py-2">
              <span
                className={cn(
                  "h-2 w-2 rounded-full",
                  dashboard.status === "online" && "bg-emerald-300 shadow-[0_0_10px_rgba(110,231,183,0.8)]",
                  dashboard.status === "connecting" && "bg-amber-300 shadow-[0_0_10px_rgba(252,211,77,0.8)]",
                  dashboard.status === "offline" && "bg-rose-300 shadow-[0_0_10px_rgba(253,164,175,0.8)]",
                )}
              />
              <span className="font-display text-[9px] tracking-[0.18em] text-jarvis-dim">
                {dashboard.status.toUpperCase()}
              </span>
            </div>
            <Button
              variant="outline"
              className="border-jarvis-border/50 bg-muted/20 text-jarvis-bright hover:bg-primary/10"
              onClick={() => setApprovalMode((value) => !value)}
            >
              <ShieldCheck className={approvalMode ? "text-emerald-300" : "text-jarvis-dim"} />
              {approvalMode ? "Approval Armed" : "Auto Review"}
            </Button>
            <Button
              className="bg-primary/15 text-primary hover:bg-primary/25"
              onClick={() => setIsPaused((value) => !value)}
            >
              {isPaused ? <Play /> : <Pause />}
              {isPaused ? "Resume" : "Pause"}
            </Button>
          </div>
        </header>

        <section className="grid flex-1 gap-4 xl:grid-cols-[300px_minmax(520px,1fr)_420px]">
          <aside className="space-y-4">
            <Panel title="Mission Queue" icon={<Layers3 className="h-4 w-4" />}>
              <div className="space-y-3">
                {displayMissions.map((mission) => (
                  <button
                    key={mission.id}
                    onClick={() => setActiveMission(mission.id)}
                    className={cn(
                      "w-full rounded-md border p-3 text-left transition-all",
                      activeMission === mission.id
                        ? "border-primary/70 bg-primary/10 shadow-lg shadow-primary/10"
                        : "border-jarvis-border/25 bg-muted/15 hover:border-jarvis-border/60 hover:bg-muted/25",
                    )}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-display text-[11px] tracking-[0.18em] text-jarvis-bright">
                        {mission.label}
                      </span>
                      <span className="font-display text-[9px] tracking-[0.16em] text-primary">
                        {mission.status}
                      </span>
                    </div>
                    <p className="mt-2 min-h-8 font-body text-xs leading-snug text-jarvis-dim">{mission.detail}</p>
                    <Progress value={mission.progress} className="mt-3 h-1.5 rounded-sm bg-muted/50" />
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="Tool Matrix" icon={<TerminalSquare className="h-4 w-4" />}>
              <div className="grid grid-cols-2 gap-2">
                {liveToolStatus.map((tool) => {
                  const Icon = tool.icon;
                  return (
                    <div key={tool.label} className="rounded-md border border-jarvis-border/25 bg-muted/15 p-3">
                      <div className="mb-3 flex items-center justify-between">
                        <Icon className="h-4 w-4 text-primary" />
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-300 shadow-[0_0_10px_rgba(110,231,183,0.8)]" />
                      </div>
                      <p className="font-display text-[9px] tracking-[0.16em] text-jarvis-dim">{tool.label}</p>
                      <p className="mt-1 font-display text-[10px] tracking-[0.14em] text-jarvis-bright">{tool.value}</p>
                    </div>
                  );
                })}
              </div>
            </Panel>
          </aside>

          <section className="space-y-4">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {telemetry.vitals.map((vital) => {
                const Icon = vital.icon;
                return (
                  <div key={vital.label} className="glass-panel rounded-md p-3">
                    <div className="flex items-center justify-between">
                      <Icon className="h-4 w-4 text-primary" />
                      <span className="font-display text-[9px] tracking-[0.2em] text-jarvis-dim">LIVE</span>
                    </div>
                    <p className="mt-3 font-display text-xl text-foreground glow-text">{vital.value}</p>
                    <p className="font-body text-xs text-jarvis-dim">{vital.label}</p>
                  </div>
                );
              })}
            </div>

            <Panel title="Retina Live Feed" icon={<Eye className="h-4 w-4" />} className="min-h-[430px]">
              <div className="relative min-h-[370px] overflow-hidden rounded-md border border-jarvis-border/30 bg-[radial-gradient(circle_at_50%_20%,rgba(36,228,255,0.14),transparent_35%),linear-gradient(135deg,rgba(5,20,32,0.95),rgba(5,8,14,0.98))]">
                {retinaImageUrl && (
                  <img
                    src={retinaImageUrl}
                    alt=""
                    className="absolute inset-0 h-full w-full object-contain opacity-80"
                  />
                )}
                <div className="absolute inset-0 opacity-35 retina-grid" />
                <motion.div
                  className="absolute left-0 right-0 h-24 bg-gradient-to-b from-transparent via-primary/20 to-transparent"
                  animate={{ y: ["-30%", "390%"] }}
                  transition={{ duration: 3.2, repeat: Infinity, ease: "linear" }}
                />
                <div className="absolute left-7 top-7 right-7 bottom-7 rounded-md border border-primary/20" />
                <div className="absolute left-10 top-10 h-16 w-52 rounded-sm border border-jarvis-border/40 bg-background/40" />
                <div className="absolute right-12 top-20 h-24 w-44 rounded-sm border border-jarvis-border/30 bg-primary/5" />
                <div className="absolute bottom-16 left-16 right-20 h-24 rounded-sm border border-jarvis-border/30 bg-muted/10" />

                {detections.map((box, index) => (
                  <motion.div
                    key={box.label}
                    className="absolute rounded-sm border border-primary bg-primary/10 shadow-[0_0_24px_rgba(0,170,255,0.18)]"
                    style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
                    initial={{ opacity: 0, scale: 0.96 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: index * 0.18 }}
                  >
                    <span className="absolute -top-6 left-0 whitespace-nowrap rounded-sm border border-primary/40 bg-background/80 px-2 py-0.5 font-display text-[9px] tracking-[0.12em] text-primary">
                      {box.label} {box.confidence}%
                    </span>
                  </motion.div>
                ))}

                <motion.div
                  className="absolute h-8 w-8 rounded-full border border-amber-300/80"
                  animate={{ left: ["62%", "66%", "62%"], top: ["32%", "36%", "32%"] }}
                  transition={{ duration: 2.6, repeat: Infinity, ease: "easeInOut" }}
                >
                  <MousePointer2 className="absolute left-3 top-3 h-5 w-5 text-amber-200" />
                </motion.div>

                <div className="absolute bottom-4 left-4 right-4 flex flex-wrap items-center justify-between gap-2 rounded-md border border-jarvis-border/30 bg-background/70 px-3 py-2 backdrop-blur">
                  <div className="flex items-center gap-2">
                    <CircleDot className={cn("h-4 w-4", isPaused ? "text-amber-300" : "text-emerald-300")} />
                    <span className="font-display text-[10px] tracking-[0.2em] text-jarvis-bright">
                      {isPaused ? "MISSION PAUSED" : retinaImageUrl ? "LIVE RETINA FRAME" : "OBSERVING ACTIVE VIEWPORT"}
                    </span>
                  </div>
                  <span className="font-body text-xs text-jarvis-dim">
                    {dashboard.latestVisionFrame
                      ? formatVisionFrame(dashboard.latestVisionFrame)
                      : "Next action: verify target before execution"}
                  </span>
                </div>
              </div>
            </Panel>
          </section>

          <aside className="space-y-4">
            <Panel title="Execution Tree" icon={<Command className="h-4 w-4" />}>
              <div className="space-y-3">
                {executionNodes.map((node, index) => (
                  <div key={node.label} className="relative flex gap-3">
                    {index < executionNodes.length - 1 && (
                      <div className="absolute left-[7px] top-5 h-full w-px bg-jarvis-border/30" />
                    )}
                    <div
                      className={cn(
                        "relative z-10 mt-1 h-3.5 w-3.5 rounded-full border",
                        node.state === "complete" && "border-emerald-300 bg-emerald-300/30",
                        node.state === "active" && "border-primary bg-primary/40 shadow-[0_0_18px_rgba(0,170,255,0.65)]",
                        node.state === "pending" && "border-jarvis-border bg-muted/30",
                      )}
                    />
                    <div className="flex-1 rounded-md border border-jarvis-border/20 bg-muted/10 p-2.5">
                      <div className="flex items-center justify-between">
                        <p className="font-display text-[10px] tracking-[0.18em] text-jarvis-bright">{node.label}</p>
                        <p className="font-display text-[8px] tracking-[0.16em] text-primary">{node.state.toUpperCase()}</p>
                      </div>
                      <p className="mt-1 font-body text-xs text-jarvis-dim">{node.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Command Lane" icon={<MessageSquareText className="h-4 w-4" />}>
              <div className="mb-3 flex items-center justify-between rounded-md border border-jarvis-border/25 bg-muted/15 p-2">
                <div>
                  <p className="font-display text-[10px] tracking-[0.2em] text-jarvis-bright">
                    {isResponding ? "J.A.R.V.I.S THINKING" : "VOICE CHANNEL"}
                  </p>
                  <p className="font-body text-xs text-jarvis-dim">{isListening ? "Listening for operator input" : "Wake system available"}</p>
                </div>
                <VoiceButton isListening={isListening} onToggle={toggleListening} />
              </div>
              <EnhancedChatPanel
                messages={messages}
                onSendMessage={sendMessage}
                isResponding={isResponding}
              />
            </Panel>
          </aside>
        </section>

        <footer className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto]">
          <Panel title="Live Event Stream" icon={<Activity className="h-4 w-4" />} compact>
            <div className="grid gap-2 md:grid-cols-5">
              {(dashboard.latestEvents.length ? dashboard.latestEvents.slice(0, 5) : fallbackEvents).map((event) => (
                <div
                  key={`${event.type}-${event.id ?? event.timestamp ?? formatEvent(event)}`}
                  className={cn(
                    "rounded-md border bg-muted/15 px-3 py-2 font-mono text-[10px]",
                    event.level === "error"
                      ? "border-rose-400/35 text-rose-200"
                      : "border-jarvis-border/25 text-jarvis-dim",
                  )}
                >
                  {formatEvent(event)}
                </div>
              ))}
            </div>
          </Panel>
          <div className="glass-panel flex items-center gap-2 rounded-md p-3">
            <Button variant="outline" size="icon" className="border-jarvis-border/40 bg-muted/20 text-primary hover:bg-primary/10" aria-label="Reset mission">
              <RotateCcw />
            </Button>
            <Button variant="outline" size="icon" className="border-rose-400/40 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20" aria-label="Stop mission">
              <Square />
            </Button>
            <Button className="bg-emerald-400/15 text-emerald-200 hover:bg-emerald-400/25">
              <CheckCircle2 />
              Approve
            </Button>
          </div>
        </footer>
      </main>
    </div>
  );
}

const fallbackEvents: DashboardEvent[] = [
  { type: "vision.frame", source: "demo", payload: { message: "captured 1920x1080 source=browser" } },
  { type: "retina.detection", source: "demo", payload: { message: "search_field confidence=0.98" } },
  { type: "planner.node", source: "demo", payload: { message: "selected BrowserTool.search" } },
  { type: "executor.awaiting", source: "demo", payload: { message: "operator approval" } },
  { type: "health.latency", source: "demo", payload: { message: "p95=812ms" } },
];

function formatEvent(event: DashboardEvent) {
  const payload = event.payload ?? {};
  const message = payload.message;
  if (typeof message === "string") return `${event.type} ${message}`;

  const pieces = Object.entries(payload)
    .slice(0, 3)
    .map(([key, value]) => `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`);
  return [event.type, ...pieces].join(" ");
}

function compactValue(value: string) {
  if (value.length <= 12) return value.toUpperCase();
  return value.split(":")[0].slice(-12).toUpperCase();
}

function formatVisionFrame(frame: NonNullable<ReturnType<typeof useDashboardEvents>["latestVisionFrame"]>) {
  const source = frame.source ?? "retina";
  const size = frame.width && frame.height ? `${frame.width}x${frame.height}` : "frame";
  const weight = frame.size_kb ? `${frame.size_kb}KB` : "";
  return [source, size, weight].filter(Boolean).join(" | ");
}

function Panel({
  title,
  icon,
  children,
  className,
  compact = false,
}: {
  title: string;
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
      className={cn("glass-panel rounded-md p-4 shadow-2xl shadow-primary/5", className)}
    >
      <div className={cn("flex items-center justify-between", compact ? "mb-2" : "mb-4")}>
        <div className="flex items-center gap-2 text-primary">
          {icon}
          <h2 className="font-display text-[11px] tracking-[0.24em] text-primary glow-text">{title}</h2>
        </div>
        <span className="h-1.5 w-1.5 rounded-full bg-primary shadow-[0_0_12px_rgba(0,170,255,0.8)]" />
      </div>
      {children}
    </motion.section>
  );
}
