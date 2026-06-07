import { motion } from "framer-motion";
import { CheckCircle2, Loader2, AlertTriangle, Circle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

export interface TimelineNode {
  label: string;
  state: "complete" | "active" | "failed" | "pending";
  detail: string;
  retryCount?: number;
  maxRetries?: number;
}

interface MissionTimelineProps {
  nodes: TimelineNode[];
  isPaused?: boolean;
}

export default function MissionTimeline({
  nodes,
  isPaused = false,
}: MissionTimelineProps) {
  return (
    <div className="space-y-4">
      {nodes.map((node, index) => {
        const isComplete = node.state === "complete";
        const isActive = node.state === "active";
        const isFailed = node.state === "failed";
        const isPending = node.state === "pending";

        return (
          <div key={node.label} className="relative flex gap-4">
            {/* Thread Connector Line */}
            {index < nodes.length - 1 && (
              <div 
                className={cn(
                  "absolute left-[11px] top-6 w-px h-[calc(100%-8px)] transition-colors duration-300",
                  isComplete ? "bg-emerald-500/50" : "bg-jarvis-border/30"
                )} 
              />
            )}

            {/* Stepper Status Icon */}
            <div className="relative flex items-center justify-center w-6 h-6 mt-1 flex-shrink-0">
              {isComplete && (
                <motion.div
                  initial={{ scale: 0.8 }}
                  animate={{ scale: 1 }}
                  className="text-emerald-400 drop-shadow-[0_0_6px_rgba(52,211,153,0.6)]"
                >
                  <CheckCircle2 size={22} />
                </motion.div>
              )}

              {isActive && (
                <div className="relative">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 2, repeat: Infinity, ease: "linear" }}
                    className={cn(
                      "text-primary",
                      isPaused ? "animate-none" : ""
                    )}
                  >
                    {isPaused ? <Circle size={22} className="text-amber-400" /> : <Loader2 size={22} />}
                  </motion.div>
                  <span className="absolute inset-0 rounded-full bg-primary/20 animate-ping" />
                </div>
              )}

              {isFailed && (
                <motion.div
                  animate={{ scale: [1, 1.1, 1] }}
                  transition={{ repeat: Infinity, duration: 1.5 }}
                  className="text-accent drop-shadow-[0_0_6px_rgba(244,63,94,0.6)]"
                >
                  <AlertTriangle size={22} />
                </motion.div>
              )}

              {isPending && (
                <Circle size={22} className="text-jarvis-dim/40" />
              )}
            </div>

            {/* Step Detail Card */}
            <motion.div 
              layout
              className={cn(
                "flex-1 rounded-xl border p-3 transition-all duration-300 bg-muted/10",
                isActive && "border-primary/60 bg-primary/5 shadow-md shadow-primary/5 glow-border",
                isComplete && "border-emerald-500/20 bg-emerald-500/5",
                isFailed && "border-accent/40 bg-accent/5",
                isPending && "border-jarvis-border/15 opacity-50"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-display text-[11px] tracking-[0.18em] font-bold text-jarvis-bright">
                  {node.label.toUpperCase()}
                </span>
                
                {isActive && node.retryCount && (
                  <span className="flex items-center gap-1 font-display text-[8px] tracking-wider text-amber-300 px-1.5 py-0.5 rounded bg-amber-400/10 border border-amber-400/20 animate-pulse">
                    <RefreshCw size={8} className="animate-spin" /> RETRY {node.retryCount}/{node.maxRetries || 3}
                  </span>
                )}

                <span 
                  className={cn(
                    "font-display text-[8px] tracking-[0.16em]",
                    isComplete && "text-emerald-400",
                    isActive && "text-primary animate-pulse",
                    isFailed && "text-accent",
                    isPending && "text-jarvis-dim/40"
                  )}
                >
                  {isPaused && isActive ? "PAUSED" : node.state.toUpperCase()}
                </span>
              </div>
              <p className="mt-1.5 font-body text-xs leading-relaxed text-jarvis-dim">
                {node.detail}
              </p>
            </motion.div>
          </div>
        );
      })}
    </div>
  );
}
