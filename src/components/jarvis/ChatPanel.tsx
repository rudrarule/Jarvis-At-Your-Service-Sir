import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Send } from "lucide-react";

interface Message {
  id: number;
  text: string;
  sender: "user" | "jarvis";
}

const initialMessages: Message[] = [
  { id: 1, text: "System initialized. All modules online.", sender: "jarvis" },
  { id: 2, text: "Hello Jarvis", sender: "user" },
  { id: 3, text: "Good evening. How can I assist you today?", sender: "jarvis" },
];

export default function ChatPanel() {
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const jarvisResponses = [
    "Analyzing your request. Processing complete.",
    "All systems are functioning within normal parameters.",
    "I've updated the holographic display accordingly.",
    "Running diagnostics now. Stand by.",
    "Understood. Executing protocol.",
    "I've cross-referenced the data. Here are my findings.",
  ];

  const sendMessage = () => {
    if (!input.trim()) return;
    const userMsg: Message = { id: Date.now(), text: input, sender: "user" };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    setTimeout(() => {
      const response = jarvisResponses[Math.floor(Math.random() * jarvisResponses.length)];
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, text: response, sender: "jarvis" },
      ]);
    }, 1000 + Math.random() * 1000);
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 60 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.8, delay: 0.5 }}
      className="glass-panel flex flex-col w-80 h-[420px] p-4"
    >
      <h2 className="font-display text-xs tracking-[0.3em] text-primary mb-3 glow-text">
        COMMUNICATIONS
      </h2>
      <div className="neon-line mb-3" />

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 pr-1 scrollbar-thin">
        <AnimatePresence>
          {messages.map((msg) => (
            <motion.div
              key={msg.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
              className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] px-3 py-2 rounded-lg text-sm font-body ${
                  msg.sender === "user"
                    ? "bg-primary/20 text-foreground border border-primary/30"
                    : "bg-muted/50 text-jarvis-bright border border-jarvis-border/30"
                }`}
              >
                {msg.sender === "jarvis" && (
                  <span className="text-[10px] font-display tracking-widest text-primary/70 block mb-1">
                    JARVIS
                  </span>
                )}
                {msg.text}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      <div className="neon-line mt-3 mb-3" />

      <div className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && sendMessage()}
          placeholder="Type a command..."
          className="flex-1 bg-muted/30 border border-jarvis-border/40 rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-jarvis-dim font-body focus:outline-none focus:border-primary/60 transition-colors"
        />
        <motion.button
          whileHover={{ scale: 1.1 }}
          whileTap={{ scale: 0.95 }}
          onClick={sendMessage}
          className="w-9 h-9 flex items-center justify-center rounded-lg border border-primary/40 text-primary hover:bg-primary/10 transition-colors"
        >
          <Send size={16} />
        </motion.button>
      </div>
    </motion.div>
  );
}
