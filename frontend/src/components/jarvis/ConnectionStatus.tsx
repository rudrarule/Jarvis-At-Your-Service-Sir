import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Wifi, WifiOff, RefreshCw } from "lucide-react";

interface ConnectionStatusProps {
  backendUrl?: string;
  checkInterval?: number;
}

export default function ConnectionStatus({
  backendUrl = "http://localhost:8082",
  checkInterval = 5000,
}: ConnectionStatusProps) {
  const [isOnline, setIsOnline] = useState<boolean | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const checkConnection = async () => {
    setIsChecking(true);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3000);

      const response = await fetch(`${backendUrl}/health`, {
        method: "GET",
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      setIsOnline(response.ok);
    } catch {
      setIsOnline(false);
    } finally {
      setIsChecking(false);
      setLastChecked(new Date());
    }
  };

  useEffect(() => {
    checkConnection();
    const interval = setInterval(checkConnection, checkInterval);
    return () => clearInterval(interval);
  }, [backendUrl, checkInterval]);

  // Don't show anything while loading initial state
  if (isOnline === null) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`fixed top-4 right-4 z-50 flex items-center gap-2 px-3 py-1.5 rounded-full glass-panel ${
        isOnline ? "border-emerald-500/30" : "border-rose-500/30"
      }`}
    >
      {/* Status Icon with Pulse */}
      <div className="relative">
        {isOnline ? (
          <>
            <Wifi size={14} className="text-emerald-400 relative z-10" />
            <motion.div
              className="absolute inset-0 rounded-full bg-emerald-400/30"
              animate={{ scale: [1, 1.5], opacity: [0.5, 0] }}
              transition={{ duration: 1.5, repeat: Infinity }}
            />
          </>
        ) : (
          <WifiOff size={14} className="text-rose-400" />
        )}
      </div>

      {/* Status Text */}
      <span
        className={`text-[10px] font-display tracking-wider ${
          isOnline ? "text-emerald-400" : "text-rose-400"
        }`}
      >
        {isOnline ? "ONLINE" : "OFFLINE"}
      </span>

      {/* Reconnect Button (when offline) */}
      <AnimatePresence>
        {!isOnline && (
          <motion.button
            initial={{ opacity: 0, width: 0 }}
            animate={{ opacity: 1, width: "auto" }}
            exit={{ opacity: 0, width: 0 }}
            onClick={checkConnection}
            disabled={isChecking}
            className="ml-1 p-1 rounded hover:bg-white/10 transition-colors"
            title="Retry connection"
          >
            <motion.div
              animate={isChecking ? { rotate: 360 } : {}}
              transition={{ duration: 1, repeat: isChecking ? Infinity : 0, ease: "linear" }}
            >
              <RefreshCw size={12} className="text-rose-300" />
            </motion.div>
          </motion.button>
        )}
      </AnimatePresence>

      {/* Tooltip on hover */}
      {lastChecked && (
        <div className="absolute opacity-0 hover:opacity-100 transition-opacity -bottom-8 right-0 text-[9px] text-jarvis-dim whitespace-nowrap">
          Last checked: {lastChecked.toLocaleTimeString()}
        </div>
      )}
    </motion.div>
  );
}
