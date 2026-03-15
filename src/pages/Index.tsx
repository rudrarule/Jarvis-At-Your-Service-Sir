import { useState, useCallback } from "react";
import { motion } from "framer-motion";
import ParticleBackground from "@/components/jarvis/ParticleBackground";
import AICore from "@/components/jarvis/AICore";
import Waveform from "@/components/jarvis/Waveform";
import ChatPanel from "@/components/jarvis/ChatPanel";
import VoiceButton from "@/components/jarvis/VoiceButton";
import ModeSwitch from "@/components/jarvis/ModeSwitch";
import HolographicPanels from "@/components/jarvis/HolographicPanels";

const Index = () => {
  const [isListening, setIsListening] = useState(false);
  const [mode, setMode] = useState<"chat" | "automation">("chat");
  const [isResponding] = useState(false);

  const toggleListening = useCallback(() => {
    setIsListening((prev) => !prev);
  }, []);

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === "chat" ? "automation" : "chat"));
  }, []);

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-background">
      {/* Particle background */}
      <ParticleBackground />

      {/* Scanline overlay */}
      <div className="absolute inset-0 z-[1] scanline pointer-events-none" />

      {/* Top bar */}
      <div className="absolute top-4 left-0 right-0 z-20 flex items-center justify-between px-6">
        <motion.div
          initial={{ opacity: 0, x: -30 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6 }}
        >
          <h1 className="font-display text-sm tracking-[0.4em] text-primary glow-text">
            J.A.R.V.I.S
          </h1>
          <p className="font-body text-xs text-jarvis-dim tracking-wider">
            Just A Rather Very Intelligent System
          </p>
        </motion.div>

        <ModeSwitch mode={mode} onToggle={toggleMode} />
      </div>

      {/* Main content area */}
      <div className="absolute inset-0 z-10 flex items-center justify-center">
        <div className="flex items-center gap-8 lg:gap-16">
          {/* Left panels */}
          <motion.div
            initial={{ opacity: 0, x: -40 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.8, delay: 0.3 }}
            className="hidden lg:block"
          >
            <HolographicPanels />
          </motion.div>

          {/* Center: AI Core + Waveform + Voice Button */}
          <div className="flex flex-col items-center gap-4">
            <AICore isListening={isListening} isResponding={isResponding} />
            <Waveform isActive={isListening} />
            <VoiceButton isListening={isListening} onToggle={toggleListening} />
          </div>

          {/* Right: Chat Panel */}
          <div className="hidden md:block">
            <ChatPanel />
          </div>
        </div>
      </div>

      {/* Bottom status bar */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 1 }}
        className="absolute bottom-4 left-0 right-0 z-20 flex justify-center"
      >
        <div className="glass-panel px-6 py-2 flex items-center gap-6">
          <StatusDot label="NEURAL NET" active />
          <StatusDot label="VOICE" active={isListening} />
          <StatusDot label="MODE" value={mode.toUpperCase()} />
        </div>
      </motion.div>
    </div>
  );
};

function StatusDot({
  label,
  active = true,
  value,
}: {
  label: string;
  active?: boolean;
  value?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <div
        className="w-2 h-2 rounded-full"
        style={{
          background: active ? "hsl(200 100% 50%)" : "hsl(200 30% 25%)",
          boxShadow: active ? "0 0 8px hsl(200 100% 50% / 0.6)" : "none",
        }}
      />
      <span className="font-display text-[9px] tracking-[0.2em] text-jarvis-dim">
        {label}
      </span>
      {value && (
        <span className="font-display text-[9px] tracking-wider text-primary">
          {value}
        </span>
      )}
    </div>
  );
}

export default Index;
