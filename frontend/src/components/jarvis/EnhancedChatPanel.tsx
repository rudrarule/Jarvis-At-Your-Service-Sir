import { useState, useRef, useEffect, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send, Copy, Check, AlertCircle, X, Sparkles } from "lucide-react";
import type { Message } from "@/hooks/useJarvis";
import CommandSuggestions from "./CommandSuggestions";

interface EnhancedChatPanelProps {
  messages?: Message[];
  onSendMessage?: (text: string) => void;
  isResponding?: boolean;
  error?: string | null;
  onRetry?: () => void;
  onCancel?: () => void;
}

interface EnhancedMessage extends Message {
  timestamp: Date;
  status?: "sending" | "sent" | "error";
}

// Message Skeleton for loading state
function MessageSkeleton() {
  return (
    <div className="flex justify-start mb-4">
      <div className="max-w-[85%] space-y-2">
        <div className="flex items-center gap-2 mb-1">
          <div className="w-8 h-8 rounded-full bg-primary/20 animate-pulse" />
          <div className="w-16 h-3 bg-primary/20 rounded animate-pulse" />
        </div>
        <div className="space-y-2">
          <div className="w-48 h-4 bg-jarvis-border/30 rounded animate-pulse" />
          <div className="w-32 h-4 bg-jarvis-border/30 rounded animate-pulse" />
          <div className="w-40 h-4 bg-jarvis-border/30 rounded animate-pulse" />
        </div>
      </div>
    </div>
  );
}

// Timestamp formatter
function formatTime(date: Date): string {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// Copy button component
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy:", err);
    }
  }, [text]);

  return (
    <motion.button
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      whileHover={{ scale: 1.1 }}
      whileTap={{ scale: 0.9 }}
      onClick={handleCopy}
      className="p-1 rounded hover:bg-white/10 transition-colors"
      title={copied ? "Copied!" : "Copy message"}
    >
      {copied ? (
        <Check size={12} className="text-emerald-400" />
      ) : (
        <Copy size={12} className="text-jarvis-dim hover:text-primary" />
      )}
    </motion.button>
  );
}

export default function EnhancedChatPanel({
  messages: externalMessages,
  onSendMessage,
  isResponding = false,
  error = null,
  onRetry,
  onCancel,
}: EnhancedChatPanelProps) {
  const [input, setInput] = useState("");
  const [isInputFocused, setIsInputFocused] = useState(false);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Show suggestions when input starts with "/" or is empty and focused
  useEffect(() => {
    if (input.startsWith("/") || (input === "" && isInputFocused)) {
      setShowSuggestions(true);
    } else {
      setShowSuggestions(false);
    }
  }, [input, isInputFocused]);

  // Add timestamps to messages
  const displayMessages: EnhancedMessage[] = (externalMessages ?? [
    { id: 1, text: "System initialized. All modules online.", sender: "jarvis" as const },
  ]).map((msg) => ({
    ...msg,
    timestamp: new Date(),
  }));

  // Auto-scroll to bottom
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [displayMessages, isResponding]);

  const sendMessage = () => {
    if (!input.trim()) return;
    if (onSendMessage) {
      onSendMessage(input);
    }
    setInput("");
  };

  // Keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    if (e.key === "Escape") {
      setInput("");
      inputRef.current?.blur();
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 60 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.8, delay: 0.5 }}
      className="glass-panel flex flex-col w-80 lg:w-96 h-[480px] p-4 shadow-2xl shadow-primary/5"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-primary" />
          <h2 className="font-display text-xs tracking-[0.3em] text-primary glow-text">
            COMMUNICATIONS
          </h2>
        </div>
        <span className="text-[9px] text-jarvis-dim font-display tracking-wider">
          {displayMessages.length} MESSAGES
        </span>
      </div>

      <div className="neon-line mb-3" />

      {/* Error Banner */}
      <AnimatePresence>
        {error && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-3 p-2 rounded-lg bg-rose-500/20 border border-rose-500/30 flex items-start gap-2"
          >
            <AlertCircle size={14} className="text-rose-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="text-xs text-rose-200 font-body">{error}</p>
              {onRetry && (
                <button
                  onClick={onRetry}
                  className="text-[10px] text-rose-300 underline hover:text-rose-200 mt-1"
                >
                  Retry
                </button>
              )}
            </div>
            <button className="text-rose-400 hover:text-rose-300">
              <X size={14} />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Messages */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto space-y-4 pr-1 scrollbar-thin scrollbar-thumb-primary/30 scrollbar-track-transparent"
      >
        <AnimatePresence mode="popLayout">
          {displayMessages.map((msg, index) => (
            <motion.div
              key={msg.id}
              layout
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ duration: 0.3, delay: index * 0.05 }}
              className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[90%] group relative ${
                  msg.sender === "user" ? "items-end" : "items-start"
                }`}
              >
                {/* Avatar for JARVIS */}
                {msg.sender === "jarvis" && (
                  <div className="flex items-center gap-2 mb-1.5">
                    <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center border border-primary/30">
                      <span className="text-[8px] font-display text-primary">J</span>
                    </div>
                    <span className="text-[10px] font-display tracking-widest text-primary/70">
                      J.A.R.V.I.S
                    </span>
                    <span className="text-[9px] text-jarvis-dim">
                      {formatTime(msg.timestamp)}
                    </span>
                  </div>
                )}

                {/* Message Bubble */}
                <div
                  className={`px-4 py-2.5 rounded-2xl text-sm font-body relative ${
                    msg.sender === "user"
                      ? "bg-primary/20 text-foreground border border-primary/30 rounded-br-md"
                      : "bg-muted/50 text-jarvis-bright border border-jarvis-border/30 rounded-bl-md"
                  }`}
                >
                  {/* Copy button (hover) */}
                  {msg.sender === "jarvis" && (
                    <div className="absolute -right-8 top-0 opacity-0 group-hover:opacity-100 transition-opacity">
                      <CopyButton text={msg.text} />
                    </div>
                  )}

                  <p className="leading-relaxed">{msg.text}</p>

                  {/* User timestamp */}
                  {msg.sender === "user" && (
                    <span className="text-[9px] text-jarvis-dim mt-1 block text-right">
                      {formatTime(msg.timestamp)}
                    </span>
                  )}
                </div>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {/* Thinking/Loading State */}
        <AnimatePresence>
          {isResponding && <MessageSkeleton />}
        </AnimatePresence>
      </div>

      <div className="neon-line mt-3 mb-3" />

      {/* Command Suggestions */}
      <div className="relative">
        <CommandSuggestions
          isVisible={showSuggestions}
          onClose={() => setShowSuggestions(false)}
          onSelect={(cmd) => {
            setInput(cmd + " ");
            inputRef.current?.focus();
          }}
          inputValue={input}
        />
      </div>

      {/* Input Area */}
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onFocus={() => setIsInputFocused(true)}
            onBlur={() => {
              // Delay to allow clicking suggestions
              setTimeout(() => setIsInputFocused(false), 200);
            }}
            placeholder="Type / for commands... (Enter to send)"
            disabled={isResponding}
            className="w-full bg-muted/30 border border-jarvis-border/40 rounded-xl px-4 py-3 pr-10 text-sm text-foreground placeholder:text-jarvis-dim/70 font-body focus:outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30 transition-all disabled:opacity-50"
          />

          {/* Focus indicator */}
          <AnimatePresence>
            {isInputFocused && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-jarvis-dim"
              >
                <span className="font-display tracking-wider">↵ ENTER</span>
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={sendMessage}
          disabled={!input.trim() || isResponding}
          className="w-12 h-12 flex items-center justify-center rounded-xl border border-primary/40 text-primary hover:bg-primary/10 transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-primary/10"
        >
          <Send size={18} className={input.trim() ? "translate-x-0.5 -translate-y-0.5" : ""} />
        </motion.button>
      </div>

      {/* Cancel button during response */}
      <AnimatePresence>
        {isResponding && onCancel && (
          <motion.button
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            onClick={onCancel}
            className="mt-2 text-[10px] text-rose-400 hover:text-rose-300 underline font-body"
          >
            Cancel response
          </motion.button>
        )}
      </AnimatePresence>

      {/* Keyboard shortcuts hint */}
      <div className="mt-2 flex items-center justify-between text-[9px] text-jarvis-dim/60">
        <span className="font-body">Press <kbd className="px-1 py-0.5 rounded bg-muted/50">ESC</kbd> to clear</span>
        <span className="font-body">Press <kbd className="px-1 py-0.5 rounded bg-muted/50">/</kbd> to focus</span>
      </div>
    </motion.div>
  );
}
