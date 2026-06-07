import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard, Database, Trash2, X } from "lucide-react";
import { Link } from "react-router-dom";
import ParticleBackground from "@/components/jarvis/ParticleBackground";
import AICore from "@/components/jarvis/AICore";
import Waveform from "@/components/jarvis/Waveform";
import EnhancedChatPanel from "@/components/jarvis/EnhancedChatPanel";
import VoiceButton from "@/components/jarvis/VoiceButton";
import ModeSwitch from "@/components/jarvis/ModeSwitch";
import HolographicPanels from "@/components/jarvis/HolographicPanels";
import ConnectionStatus from "@/components/jarvis/ConnectionStatus";
import KeyboardShortcuts from "@/components/jarvis/KeyboardShortcuts";
import { useJarvis } from "@/hooks/useJarvis";
import { useJarvisWake } from "@/hooks/useJarvisWake";
import { useIsMobile } from "@/hooks/use-mobile";
import MobileTabs, { TabType } from "@/components/jarvis/MobileTabs";

const Index = () => {
  const [mode, setMode] = useState<"chat" | "automation">("chat");
  const [showShortcuts, setShowShortcuts] = useState(false);
  const [backendError, setBackendError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabType>("chat");
  const [isMemoryOpen, setIsMemoryOpen] = useState(false);
  const [memories, setMemories] = useState<{ text: string; timestamp: string }[]>([]);

  // Theme states ("default" maps to Cyan HUD)
  const [theme, setTheme] = useState<"default" | "amber" | "crimson">(() => {
    const saved = localStorage.getItem("jarvis-theme");
    return saved === "amber" || saved === "crimson" ? saved : "default";
  });

  const isMobile = useIsMobile();
  const starkTriggerRef = useRef<() => void>();

  // Global HUD theme class injector
  useEffect(() => {
    localStorage.setItem("jarvis-theme", theme);
    const body = document.body;
    body.classList.remove("theme-amber", "theme-crimson");
    if (theme === "amber") {
      body.classList.add("theme-amber");
    } else if (theme === "crimson") {
      body.classList.add("theme-crimson");
    }
  }, [theme]);

  // Fetch ChromaDB memories
  const fetchMemories = useCallback(async () => {
    try {
      const res = await fetch(`/memory`);
      if (res.ok) {
        const data = await res.json();
        setMemories(data.memory || []);
      }
    } catch (err) {
      console.error("Failed to fetch memories:", err);
    }
  }, []);

  // Wipe ChromaDB memories
  const wipeMemory = useCallback(async () => {
    try {
      const res = await fetch(`/memory`, { method: "DELETE" });
      if (res.ok) {
        setMemories([]);
      }
    } catch (err) {
      console.error("Failed to wipe memories:", err);
    }
  }, []);

  // Fetch memories when drawer is opened or tab becomes memory
  useEffect(() => {
    if (isMemoryOpen || activeTab === "memory") {
      fetchMemories();
    }
  }, [isMemoryOpen, activeTab, fetchMemories]);

  const handleIntercept = useCallback((text: string) => {
    const cleaned = text.trim().toLowerCase();
    // remove punctuation for voice transcripts (e.g. "hey jarvis.")
    const noPunctuation = cleaned.replace(/[.,?!]/g, "");
    if (noPunctuation === "hey jarvis" || noPunctuation === "wake up") {
      if (starkTriggerRef.current) starkTriggerRef.current();
      return true; // handled
    }
    return false;
  }, []);

  const {
    isListening,
    isResponding,
    messages,
    toggleListening,
    sendMessage,
    addMessage,
  } = useJarvis(handleIntercept);

  // Voice activation: "Hey Jarvis" wake word
  const { isWakeActive, isBooting, startWakeSystem, stopWakeSystem, triggerStarkProtocol, isListeningMusic } =
    useJarvisWake(toggleListening, isListening, (text) => addMessage(text, "jarvis"), sendMessage);

  useEffect(() => {
    starkTriggerRef.current = triggerStarkProtocol;
  }, [triggerStarkProtocol]);

  const handleSendMessage = useCallback((text: string) => {
    if (!handleIntercept(text)) {
      sendMessage(text);
    }
  }, [sendMessage, handleIntercept]);

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

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Show shortcuts modal on ? (when not typing)
      if (e.key === "?" && document.activeElement?.tagName !== "INPUT") {
        setShowShortcuts(true);
      }
      // Clear error on Escape
      if (e.key === "Escape") {
        setBackendError(null);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Handle backend errors from messages
  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.text.includes("Connection to backend lost")) {
      setBackendError("Unable to connect to JARVIS backend. Please ensure the server is running on port 8000.");
    }
  }, [messages]);

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
      {/* Connection Status */}
      <ConnectionStatus />

      {/* Keyboard Shortcuts Modal */}
      <KeyboardShortcuts isOpen={showShortcuts} onClose={() => setShowShortcuts(false)} />

      {/* Particle background */}
      <ParticleBackground />

      {/* Scanline overlay */}
      <div className="absolute inset-0 z-[1] scanline pointer-events-none" />

      {/* Top bar */}
      <div className="absolute top-4 left-0 right-0 z-20 flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-6">
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

        <div className="flex flex-wrap items-center gap-3">
          {/* Holographic Theme Selection */}
          <div className="flex items-center gap-2 glass-panel px-3 py-1.5 border-primary/20">
            <span className="font-display text-[8px] tracking-[0.2em] text-jarvis-dim">HUD:</span>
            <button
              onClick={() => setTheme("default")}
              className={`w-3.5 h-3.5 rounded-full bg-cyan-400 border transition-all ${
                theme === "default"
                  ? "ring-2 ring-primary/60 scale-110 border-white shadow-[0_0_8px_rgba(0,170,255,0.8)]"
                  : "opacity-60 border-transparent hover:opacity-100"
              }`}
              title="Cyan theme"
            />
            <button
              onClick={() => setTheme("amber")}
              className={`w-3.5 h-3.5 rounded-full bg-amber-500 border transition-all ${
                theme === "amber"
                  ? "ring-2 ring-primary/60 scale-110 border-white shadow-[0_0_8px_rgba(245,158,11,0.8)]"
                  : "opacity-60 border-transparent hover:opacity-100"
              }`}
              title="Amber theme"
            />
            <button
              onClick={() => setTheme("crimson")}
              className={`w-3.5 h-3.5 rounded-full bg-rose-600 border transition-all ${
                theme === "crimson"
                  ? "ring-2 ring-primary/60 scale-110 border-white shadow-[0_0_8px_rgba(225,29,72,0.8)]"
                  : "opacity-60 border-transparent hover:opacity-100"
              }`}
              title="Crimson alert theme"
            />
          </div>

          {/* Slide-out memory drawer trigger button */}
          <button
            onClick={() => setIsMemoryOpen((prev) => !prev)}
            className={`glass-panel flex items-center gap-1.5 px-3 py-1.5 font-display text-[9px] tracking-[0.2em] transition-all hover:border-primary/60 hover:bg-primary/10 ${
              isMemoryOpen ? "border-primary/60 text-primary bg-primary/10" : "text-jarvis-dim"
            }`}
            title="Database memories"
          >
            <Database size={12} className={isMemoryOpen ? "text-primary animate-pulse" : ""} />
            <span>DB</span>
          </button>

          {/* Dashboard connection shortcut link */}
          <Link
            to="/dashboard"
            className="glass-panel group flex items-center gap-1.5 rounded-md px-3 py-1.5 font-display text-[9px] tracking-[0.2em] text-primary transition-all hover:border-primary/60 hover:bg-primary/10"
          >
            <LayoutDashboard size={12} className="transition-transform group-hover:scale-110" />
            PANEL
          </Link>

          <ModeSwitch mode={mode} onToggle={toggleMode} />
        </div>
      </div>

      {/* Main content area */}
      <div className="absolute inset-0 z-10 flex items-center justify-center p-4 pt-24 pb-20 md:pb-4">
        <div className="flex flex-col md:flex-row items-center justify-center gap-6 lg:gap-12 w-full max-w-7xl h-full max-h-[80vh] md:max-h-[85vh]">
          {/* Left panel: Vitals / Telemetry */}
          <AnimatePresence>
            {(activeTab === "vitals" || !isMobile) && (
              <motion.div
                initial={{ opacity: 0, x: -30 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -30 }}
                transition={{ duration: 0.5 }}
                className={activeTab === "vitals" && isMobile ? "flex w-full items-center justify-center" : "hidden lg:flex"}
              >
                <HolographicPanels />
              </motion.div>
            )}
          </AnimatePresence>

          {/* Center panel: AI Core + Waveform + Voice Button */}
          <AnimatePresence>
            {(activeTab === "retina" || !isMobile) && (
              <motion.div
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.95 }}
                transition={{ duration: 0.5 }}
                className={
                  activeTab === "retina" && isMobile
                    ? "flex flex-col items-center justify-center gap-4 relative w-full"
                    : "hidden md:flex flex-col items-center justify-center gap-4 relative"
                }
              >
                <AICore isListening={isListening || isListeningMusic} isResponding={isResponding || isBooting} />
                <Waveform isActive={isListening || isResponding || isBooting || isListeningMusic} />

                {isListeningMusic && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="absolute -bottom-8 whitespace-nowrap font-display text-xs tracking-[0.2em] text-jarvis-dim animate-pulse"
                  >
                    Listening for response...
                  </motion.div>
                )}

                <div className="mt-4">
                  <VoiceButton isListening={isListening} onToggle={handleManualMicToggle} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Right panel: Enhanced Chat Panel */}
          <AnimatePresence>
            {(activeTab === "chat" || !isMobile) && (
              <motion.div
                initial={{ opacity: 0, x: 30 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 30 }}
                transition={{ duration: 0.5 }}
                className={activeTab === "chat" && isMobile ? "flex w-full items-center justify-center" : "hidden md:flex"}
              >
                <EnhancedChatPanel
                  messages={messages}
                  onSendMessage={handleSendMessage}
                  isResponding={isResponding}
                  error={backendError}
                  onRetry={() => setBackendError(null)}
                />
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* Collapsible Slide-out Memory Drawer */}
      <AnimatePresence>
        {(isMemoryOpen || (isMobile && activeTab === "memory")) && (
          <motion.div
            initial={{ x: "100%", opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: "100%", opacity: 0 }}
            transition={{ type: "spring", damping: 25, stiffness: 200 }}
            className="fixed top-0 right-0 h-screen w-full sm:w-[400px] bg-background/90 backdrop-blur-xl border-l border-primary/20 z-40 p-6 shadow-2xl flex flex-col pt-24"
          >
            {/* Drawer Header */}
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Database size={16} className="text-primary animate-pulse" />
                <h2 className="font-display text-xs tracking-[0.3em] text-primary glow-text">
                  NEURAL DATABASE
                </h2>
              </div>
              <button
                onClick={() => {
                  setIsMemoryOpen(false);
                  if (activeTab === "memory") {
                    setActiveTab("chat");
                  }
                }}
                className="p-1 rounded-md border border-jarvis-border/40 text-jarvis-dim hover:text-rose-400 hover:border-rose-400/40 transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <div className="neon-line mb-4" />

            {/* Controls */}
            <div className="flex items-center justify-between mb-4">
              <span className="text-[9px] text-jarvis-dim font-display tracking-widest">
                {memories.length} RECORDS STORED
              </span>
              {memories.length > 0 && (
                <button
                  onClick={() => {
                    if (window.confirm("Sir, are you sure you want to clear my neural database? This action is irreversible.")) {
                      wipeMemory();
                    }
                  }}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded border border-rose-500/30 text-rose-400 bg-rose-500/5 hover:bg-rose-500/10 font-display text-[9px] tracking-widest transition-all"
                >
                  <Trash2 size={10} /> WIPE CORES
                </button>
              )}
            </div>

            {/* Memory list */}
            <div className="flex-1 overflow-y-auto pr-1 space-y-3 scrollbar-thin scrollbar-thumb-primary/20">
              {memories.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center p-6 border border-dashed border-jarvis-border/20 rounded-xl">
                  <Database size={24} className="text-jarvis-dim/30 mb-2" />
                  <p className="font-body text-xs text-jarvis-dim">
                    No persistent memories found in ChromaDB.
                  </p>
                  <p className="font-body text-[10px] text-jarvis-dim/60 mt-1 max-w-[240px]">
                    Interactions and preferences will be logged here as you converse with J.A.R.V.I.S.
                  </p>
                </div>
              ) : (
                memories.map((mem, i) => (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: i * 0.05 }}
                    className="glass-panel border-jarvis-border/30 bg-muted/20 p-3 rounded-lg flex flex-col gap-1.5"
                  >
                    <p className="font-body text-xs text-jarvis-bright leading-relaxed">
                      {mem.text}
                    </p>
                    {mem.timestamp && (
                      <span className="font-display text-[8px] text-jarvis-dim/60 self-end">
                        {new Date(mem.timestamp).toLocaleString()}
                      </span>
                    )}
                  </motion.div>
                ))
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Mobile Tabs Bottom Switcher */}
      <MobileTabs activeTab={activeTab} onChangeTab={setActiveTab} />

      {/* Bottom status bar (desktop/tablet only) */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 1 }}
        className="absolute bottom-4 left-0 right-0 z-20 hidden md:flex justify-center"
      >
        <div className="glass-panel px-6 py-2 flex items-center gap-6">
          <StatusDot label="SYSTEM" value={isResponding ? "THINKING" : "IDLE"} active={isResponding} />
          <StatusDot label="NEURAL NET" active />
          <StatusDot label="WAKE" active={isWakeActive} />
          <StatusDot label="VOICE" active={isListening} />
          <StatusDot label="MODE" value={mode.toUpperCase()} />

          {/* Divider */}
          <div className="w-px h-4 bg-jarvis-border/30" />

          {/* Help button */}
          <button
            onClick={() => setShowShortcuts(true)}
            className="text-[10px] font-display tracking-wider text-jarvis-dim hover:text-primary transition-colors"
            title="Keyboard shortcuts (Press ?)"
          >
            [?] HELP
          </button>
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
          background: active ? "hsl(var(--primary))" : "hsl(var(--muted-foreground) / 0.4)",
          boxShadow: active ? "0 0 8px hsl(var(--primary) / 0.6)" : "none",
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
