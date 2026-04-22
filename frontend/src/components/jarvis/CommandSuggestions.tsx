import { useState, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Command, Terminal, Search, Wrench, Globe, Music, FileText, Zap } from "lucide-react";

interface CommandSuggestion {
  id: string;
  command: string;
  description: string;
  icon: React.ReactNode;
  category: string;
}

interface CommandSuggestionsProps {
  onSelect: (command: string) => void;
  isVisible: boolean;
  onClose: () => void;
  inputValue?: string;
}

const SUGGESTIONS: CommandSuggestion[] = [
  {
    id: "1",
    command: "Search for",
    description: "Search the web",
    icon: <Search size={14} />,
    category: "Web",
  },
  {
    id: "2",
    command: "What's the weather in",
    description: "Check weather",
    icon: <Globe size={14} />,
    category: "Info",
  },
  {
    id: "3",
    command: "Play",
    description: "Play music",
    icon: <Music size={14} />,
    category: "Media",
  },
  {
    id: "4",
    command: "Create a file",
    description: "File operations",
    icon: <FileText size={14} />,
    category: "Files",
  },
  {
    id: "5",
    command: "Run",
    description: "Execute command",
    icon: <Terminal size={14} />,
    category: "System",
  },
  {
    id: "6",
    command: "Optimize",
    description: "System optimization",
    icon: <Zap size={14} />,
    category: "System",
  },
];

export default function CommandSuggestions({
  onSelect,
  isVisible,
  onClose,
  inputValue = "",
}: CommandSuggestionsProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [filteredSuggestions, setFilteredSuggestions] = useState(SUGGESTIONS);
  const containerRef = useRef<HTMLDivElement>(null);

  // Filter suggestions based on input
  useEffect(() => {
    if (!inputValue.trim()) {
      setFilteredSuggestions(SUGGESTIONS);
      return;
    }

    const filtered = SUGGESTIONS.filter(
      (s) =>
        s.command.toLowerCase().includes(inputValue.toLowerCase()) ||
        s.description.toLowerCase().includes(inputValue.toLowerCase())
    );
    setFilteredSuggestions(filtered);
    setSelectedIndex(0);
  }, [inputValue]);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isVisible) return;

      switch (e.key) {
        case "ArrowDown":
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev < filteredSuggestions.length - 1 ? prev + 1 : 0
          );
          break;
        case "ArrowUp":
          e.preventDefault();
          setSelectedIndex((prev) =>
            prev > 0 ? prev - 1 : filteredSuggestions.length - 1
          );
          break;
        case "Enter":
          e.preventDefault();
          if (filteredSuggestions[selectedIndex]) {
            onSelect(filteredSuggestions[selectedIndex].command);
            onClose();
          }
          break;
        case "Escape":
          onClose();
          break;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isVisible, filteredSuggestions, selectedIndex, onSelect, onClose]);

  // Scroll selected into view
  useEffect(() => {
    const element = containerRef.current?.children[selectedIndex] as HTMLElement;
    element?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [selectedIndex]);

  if (!isVisible || filteredSuggestions.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -10, scale: 0.95 }}
      className="absolute bottom-full left-0 right-0 mb-2 glass-panel rounded-xl overflow-hidden shadow-2xl shadow-black/50 z-50"
    >
      {/* Header */}
      <div className="px-3 py-2 border-b border-jarvis-border/30 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Command size={12} className="text-primary" />
          <span className="text-[10px] font-display tracking-wider text-jarvis-dim">
            QUICK COMMANDS
          </span>
        </div>
        <span className="text-[9px] text-jarvis-dim/60">
          Use ↑↓ to navigate, Enter to select
        </span>
      </div>

      {/* Suggestions List */}
      <div
        ref={containerRef}
        className="max-h-48 overflow-y-auto scrollbar-thin scrollbar-thumb-primary/30"
      >
        {filteredSuggestions.map((suggestion, index) => (
          <motion.button
            key={suggestion.id}
            onClick={() => {
              onSelect(suggestion.command);
              onClose();
            }}
            onMouseEnter={() => setSelectedIndex(index)}
            className={`w-full px-3 py-2.5 flex items-center gap-3 text-left transition-all ${
              index === selectedIndex
                ? "bg-primary/20 border-l-2 border-primary"
                : "border-l-2 border-transparent hover:bg-white/5"
            }`}
          >
            {/* Icon */}
            <div
              className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                index === selectedIndex
                  ? "bg-primary/30 text-primary"
                  : "bg-muted/50 text-jarvis-dim"
              }`}
            >
              {suggestion.icon}
            </div>

            {/* Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className={`text-sm font-body truncate ${
                    index === selectedIndex
                      ? "text-primary"
                      : "text-foreground"
                  }`}
                >
                  {suggestion.command}
                </span>
                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-muted/50 text-jarvis-dim font-display">
                  {suggestion.category}
                </span>
              </div>
              <span className="text-[11px] text-jarvis-dim/70 font-body">
                {suggestion.description}
              </span>
            </div>

            {/* Selected indicator */}
            <AnimatePresence>
              {index === selectedIndex && (
                <motion.div
                  initial={{ opacity: 0, x: -5 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -5 }}
                >
                  <span className="text-[10px] text-primary font-display">↵</span>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.button>
        ))}
      </div>

      {/* Footer */}
      <div className="px-3 py-1.5 border-t border-jarvis-border/30 bg-muted/20">
        <div className="flex items-center gap-4 text-[9px] text-jarvis-dim/50">
          <span className="flex items-center gap-1">
            <kbd className="px-1 rounded bg-muted">↑↓</kbd> Navigate
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1 rounded bg-muted">↵</kbd> Select
          </span>
          <span className="flex items-center gap-1">
            <kbd className="px-1 rounded bg-muted">ESC</kbd> Close
          </span>
        </div>
      </div>
    </motion.div>
  );
}
