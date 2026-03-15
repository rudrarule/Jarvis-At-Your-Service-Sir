import { motion } from "framer-motion";

interface ModeSwitchProps {
  mode: "chat" | "automation";
  onToggle: () => void;
}

export default function ModeSwitch({ mode, onToggle }: ModeSwitchProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.8 }}
      className="glass-panel px-4 py-2 flex items-center gap-3"
    >
      <span
        className={`font-display text-[10px] tracking-[0.2em] transition-colors ${
          mode === "chat" ? "text-primary glow-text" : "text-jarvis-dim"
        }`}
      >
        CHAT
      </span>

      <button
        onClick={onToggle}
        className="relative w-12 h-6 rounded-full border border-jarvis-border/60 bg-muted/30 transition-colors"
        style={{
          boxShadow: "inset 0 0 8px hsl(200 100% 50% / 0.1)",
        }}
      >
        <motion.div
          className="absolute top-[2px] w-5 h-5 rounded-full bg-primary"
          animate={{ left: mode === "chat" ? 2 : 22 }}
          transition={{ type: "spring", stiffness: 400, damping: 25 }}
          style={{
            boxShadow: "0 0 10px hsl(200 100% 50% / 0.6)",
          }}
        />
      </button>

      <span
        className={`font-display text-[10px] tracking-[0.2em] transition-colors ${
          mode === "automation" ? "text-secondary glow-text" : "text-jarvis-dim"
        }`}
      >
        AUTO
      </span>
    </motion.div>
  );
}
