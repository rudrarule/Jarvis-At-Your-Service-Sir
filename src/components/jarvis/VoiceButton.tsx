import { motion } from "framer-motion";
import { Mic, MicOff } from "lucide-react";

interface VoiceButtonProps {
  isListening: boolean;
  onToggle: () => void;
}

export default function VoiceButton({ isListening, onToggle }: VoiceButtonProps) {
  return (
    <motion.button
      onClick={onToggle}
      whileHover={{ scale: 1.08 }}
      whileTap={{ scale: 0.95 }}
      className="relative w-16 h-16 rounded-full flex items-center justify-center border-2 transition-colors"
      style={{
        borderColor: isListening
          ? "hsl(200 100% 50%)"
          : "hsl(200 60% 30%)",
        background: isListening
          ? "hsl(200 100% 50% / 0.15)"
          : "hsl(215 40% 10% / 0.8)",
        boxShadow: isListening
          ? "0 0 30px hsl(200 100% 50% / 0.5), 0 0 60px hsl(200 100% 50% / 0.2), inset 0 0 20px hsl(200 100% 50% / 0.1)"
          : "0 0 10px hsl(200 100% 50% / 0.1)",
      }}
    >
      {isListening ? (
        <MicOff size={22} className="text-primary" />
      ) : (
        <Mic size={22} className="text-primary" />
      )}

      {/* Pulse rings when listening */}
      {isListening && (
        <>
          <motion.div
            className="absolute inset-0 rounded-full border-2 border-primary/40"
            animate={{ scale: [1, 1.8], opacity: [0.5, 0] }}
            transition={{ duration: 1.5, repeat: Infinity }}
          />
          <motion.div
            className="absolute inset-0 rounded-full border border-primary/30"
            animate={{ scale: [1, 2.2], opacity: [0.3, 0] }}
            transition={{ duration: 1.5, repeat: Infinity, delay: 0.3 }}
          />
        </>
      )}
    </motion.button>
  );
}
