import { motion } from "framer-motion";

interface WaveformProps {
  isActive: boolean;
}

export default function Waveform({ isActive }: WaveformProps) {
  const barCount = 32;

  return (
    <div className="flex items-center justify-center gap-[3px] h-12">
      {Array.from({ length: barCount }).map((_, i) => {
        const delay = i * 0.05;
        const maxH = 8 + Math.sin(i * 0.5) * 20 + Math.random() * 12;

        return (
          <motion.div
            key={i}
            className="w-[3px] rounded-full"
            style={{
              background: "linear-gradient(to top, hsl(200 100% 50%), hsl(185 100% 60%))",
              boxShadow: isActive
                ? "0 0 6px hsl(200 100% 50% / 0.6)"
                : "none",
            }}
            animate={{
              height: isActive ? [4, maxH, 4] : 4,
              opacity: isActive ? [0.5, 1, 0.5] : 0.3,
            }}
            transition={{
              duration: 0.8,
              repeat: Infinity,
              delay,
              ease: "easeInOut",
            }}
          />
        );
      })}
    </div>
  );
}
