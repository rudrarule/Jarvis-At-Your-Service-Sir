import { motion } from "framer-motion";
import { Activity, Brain, Cpu, Wrench } from "lucide-react";
import { useEffect, useState } from "react";

interface PanelData {
  title: string;
  value: string;
  icon: React.ReactNode;
  subtext: string;
}

function useAnimatedValue(min: number, max: number, interval: number) {
  const [value, setValue] = useState(Math.floor(Math.random() * (max - min) + min));
  useEffect(() => {
    const id = setInterval(() => {
      setValue(Math.floor(Math.random() * (max - min) + min));
    }, interval);
    return () => clearInterval(id);
  }, [min, max, interval]);
  return value;
}

function HoloPanel({ data, index }: { data: PanelData; index: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.8, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.3 + index * 0.15 }}
      className="glass-panel p-4 w-44 animate-float"
      style={{ animationDelay: `${index * 1.5}s` }}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className="text-primary">{data.icon}</div>
        <h3 className="font-display text-[9px] tracking-[0.25em] text-jarvis-dim">
          {data.title}
        </h3>
      </div>
      <div className="font-display text-xl text-foreground glow-text">
        {data.value}
      </div>
      <div className="font-body text-xs text-jarvis-dim mt-1">{data.subtext}</div>
      <div className="neon-line mt-3" />
    </motion.div>
  );
}

export default function HolographicPanels() {
  const cpuUsage = useAnimatedValue(15, 45, 2000);
  const confidence = useAnimatedValue(88, 99, 3000);
  const activeTools = useAnimatedValue(3, 8, 4000);

  const panels: PanelData[] = [
    {
      title: "SYSTEM STATUS",
      value: "ONLINE",
      icon: <Activity size={14} />,
      subtext: "All systems nominal",
    },
    {
      title: "AI CONFIDENCE",
      value: `${confidence}%`,
      icon: <Brain size={14} />,
      subtext: "Neural net active",
    },
    {
      title: "ACTIVE TOOLS",
      value: `${activeTools}`,
      icon: <Wrench size={14} />,
      subtext: "Modules loaded",
    },
    {
      title: "CPU USAGE",
      value: `${cpuUsage}%`,
      icon: <Cpu size={14} />,
      subtext: "Processing load",
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {panels.map((panel, i) => (
        <HoloPanel key={panel.title} data={panel} index={i} />
      ))}
    </div>
  );
}
