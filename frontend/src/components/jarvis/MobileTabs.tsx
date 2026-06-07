import { MessageSquare, Eye, Cpu, Database } from "lucide-react";
import { cn } from "@/lib/utils";

export type TabType = "chat" | "vitals" | "retina" | "memory";

interface MobileTabsProps {
  activeTab: TabType;
  onChangeTab: (tab: TabType) => void;
  hasUnreadMessage?: boolean;
}

export default function MobileTabs({
  activeTab,
  onChangeTab,
  hasUnreadMessage = false,
}: MobileTabsProps) {
  const tabs = [
    { id: "chat" as TabType, label: "BUTLER", icon: MessageSquare, badge: hasUnreadMessage },
    { id: "retina" as TabType, label: "RETINA", icon: Eye },
    { id: "vitals" as TabType, label: "VITALS", icon: Cpu },
    { id: "memory" as TabType, label: "PREFS", icon: Database },
  ];

  return (
    <div className="md:hidden fixed bottom-0 left-0 right-0 z-30 px-4 pb-4 bg-gradient-to-t from-background via-background/80 to-transparent pt-6 pointer-events-none">
      <div className="glass-panel mx-auto max-w-md w-full flex items-center justify-around py-2 px-3 pointer-events-auto shadow-lg shadow-primary/5">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => onChangeTab(tab.id)}
              className={cn(
                "relative flex flex-col items-center gap-1 py-1.5 px-3 rounded-md transition-all",
                isActive 
                  ? "text-primary" 
                  : "text-jarvis-dim hover:text-jarvis-bright"
              )}
            >
              <div className="relative">
                <Icon size={20} className={cn("transition-transform", isActive && "scale-110 drop-shadow-[0_0_8px_rgba(0,170,255,0.6)]")} />
                {tab.badge && (
                  <span className="absolute -top-1.5 -right-1.5 w-2 h-2 rounded-full bg-accent animate-pulse shadow-[0_0_6px_rgba(255,0,100,0.8)]" />
                )}
              </div>
              <span className="font-display text-[8px] tracking-widest">{tab.label}</span>
              {isActive && (
                <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-0.5 rounded bg-primary shadow-[0_0_6px_rgba(0,170,255,0.8)]" />
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
