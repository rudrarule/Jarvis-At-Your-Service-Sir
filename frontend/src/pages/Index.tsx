import { useState, useCallback, useEffect, useRef } from "react";
import { motion } from "framer-motion";
import ParticleBackground from "@/components/jarvis/ParticleBackground";
import AICore from "@/components/jarvis/AICore";
import Waveform from "@/components/jarvis/Waveform";
import ChatPanel from "@/components/jarvis/ChatPanel";
import VoiceButton from "@/components/jarvis/VoiceButton";
import ModeSwitch from "@/components/jarvis/ModeSwitch";
import HolographicPanels from "@/components/jarvis/HolographicPanels";
import { useJarvis } from "@/hooks/useJarvis";
import { useJarvisWake } from "@/hooks/useJarvisWake";

const Index = () => {
  const [mode, setMode] = useState<"chat" | "automation">("chat");

  const {
    isListening,
    isResponding,
    messages,
    toggleListening,
    sendMessage,
  } = useJarvis();

  // Voice activation: "Hey Jarvis" wake word
  const { isWakeActive, startWakeSystem, stopWakeSystem } =
    useJarvisWake(toggleListening, isListening);

  // Auto-start the wake system once on mount
  const startRef = useRef(startWakeSystem);
  const stopRef = useRef(stopWakeSystem);
  startRef.current = startWakeSystem;
  stopRef.current = stopWakeSystem;

  useEffect(() => {
    // Small delay to let browser settle, then start
    const timer = setTimeout(() => startRef.current(), 500);
    return () => {
      clearTimeout(timer);
      stopRef.current();
    };
  }, []);

  const toggleMode = useCallback(() => {
    setMode((prev) => (prev === "chat" ? "automation" : "chat"));
  }, []);

  // Wrap the UI mic button so it correctly stops the wake listener before starting the main listener
  const handleManualMicToggle = useCallback(() => {
    if (!isListening) {
      // Before manually starting the mic, stop the wake word listener to avoid a conflict
      stopWakeSystem();
      
      // Delay slightly to give Chrome time to fully release the microphone
      setTimeout(() => {
        toggleListening();
      }, 350);
    } else {
      // If currently listening, just stop it normally.
      // useJarvisWake's useEffect will automatically restart the wake system 
      // when isListening becomes false.
      toggleListening();
    }
  }, [isListening, stopWakeSystem, toggleListening]);

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
            <VoiceButton isListening={isListening} onToggle={handleManualMicToggle} />
          </div>

          {/* Right: Chat Panel */}
          <div className="hidden md:block">
            <ChatPanel messages={messages} onSendMessage={sendMessage} />
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
          <StatusDot label="WAKE" active={isWakeActive} />
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
