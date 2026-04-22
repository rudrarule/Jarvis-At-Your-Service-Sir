import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { X, Keyboard, Command, Mic, MessageSquare, Zap } from "lucide-react";

interface Shortcut {
  key: string;
  description: string;
  category: "general" | "chat" | "voice" | "system";
}

const SHORTCUTS: Shortcut[] = [
  { key: "/", description: "Focus input field", category: "general" },
  { key: "ESC", description: "Clear input / Close modal", category: "general" },
  { key: "?", description: "Show keyboard shortcuts", category: "general" },
  { key: "Enter", description: "Send message", category: "chat" },
  { key: "Ctrl + Enter", description: "New line in input", category: "chat" },
  { key: "↑", description: "Previous message (edit)", category: "chat" },
  { key: "↓", description: "Next message (edit)", category: "chat" },
  { key: "Space", description: "Toggle voice input", category: "voice" },
  { key: "M", description: "Mute/Unmute", category: "voice" },
  { key: "R", description: "Retry last action", category: "system" },
  { key: "C", description: "Clear chat history", category: "system" },
];

interface KeyboardShortcutsProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function KeyboardShortcuts({ isOpen, onClose }: KeyboardShortcutsProps) {
  const [activeCategory, setActiveCategory] = useState<"all" | Shortcut["category"]>("all");

  // Close on escape
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "?" && !isOpen) {
        // Don't open if typing in input
        if (document.activeElement?.tagName === "INPUT") return;
        // Trigger open via parent
      }
      if (e.key === "Escape" && isOpen) {
        onClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  const filteredShortcuts =
    activeCategory === "all"
      ? SHORTCUTS
      : SHORTCUTS.filter((s) => s.category === activeCategory);

  const categories = [
    { id: "all", label: "All", icon: Command },
    { id: "general", label: "General", icon: Zap },
    { id: "chat", label: "Chat", icon: MessageSquare },
    { id: "voice", label: "Voice", icon: Mic },
    { id: "system", label: "System", icon: Command },
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            className="fixed inset-0 flex items-center justify-center z-50 pointer-events-none"
          >
            <div className="glass-panel w-full max-w-lg mx-4 rounded-2xl overflow-hidden shadow-2xl pointer-events-auto">
              {/* Header */}
              <div className="px-6 py-4 border-b border-jarvis-border/30 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
                    <Keyboard size={20} className="text-primary" />
                  </div>
                  <div>
                    <h2 className="font-display text-lg text-foreground">
                      Keyboard Shortcuts
                    </h2>
                    <p className="text-xs text-jarvis-dim font-body">
                      Master JARVIS with hotkeys
                    </p>
                  </div>
                </div>

                <button
                  onClick={onClose}
                  className="w-8 h-8 rounded-lg hover:bg-white/10 flex items-center justify-center transition-colors"
                >
                  <X size={18} className="text-jarvis-dim" />
                </button>
              </div>

              {/* Category Tabs */}
              <div className="px-6 py-3 border-b border-jarvis-border/30 flex gap-2 overflow-x-auto scrollbar-hide">
                {categories.map((cat) => (
                  <button
                    key={cat.id}
                    onClick={() => setActiveCategory(cat.id as typeof activeCategory)}
                    className={`px-3 py-1.5 rounded-lg text-xs font-display tracking-wider transition-all whitespace-nowrap ${
                      activeCategory === cat.id
                        ? "bg-primary/20 text-primary border border-primary/30"
                        : "text-jarvis-dim hover:text-foreground hover:bg-white/5"
                    }`}
                  >
                    {cat.label}
                  </button>
                ))}
              </div>

              {/* Shortcuts Grid */}
              <div className="p-6 max-h-[60vh] overflow-y-auto scrollbar-thin scrollbar-thumb-primary/30">
                <div className="grid grid-cols-1 gap-3">
                  {filteredShortcuts.map((shortcut, index) => (
                    <motion.div
                      key={shortcut.key}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: index * 0.03 }}
                      className="flex items-center justify-between p-3 rounded-xl bg-muted/30 border border-jarvis-border/20 hover:border-primary/30 transition-colors group"
                    >
                      <span className="text-sm text-foreground font-body">
                        {shortcut.description}
                      </span>
                      <kbd className="px-2 py-1 rounded-lg bg-muted/50 border border-jarvis-border/40 text-xs font-display text-primary group-hover:border-primary/40 transition-colors">
                        {shortcut.key}
                      </kbd>
                    </motion.div>
                  ))}
                </div>
              </div>

              {/* Footer */}
              <div className="px-6 py-3 border-t border-jarvis-border/30 bg-muted/20">
                <p className="text-xs text-jarvis-dim text-center font-body">
                  Press <kbd className="px-1 py-0.5 rounded bg-muted">ESC</kbd> to close
                </p>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
