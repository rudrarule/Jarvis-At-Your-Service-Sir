import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { ArrowRight, CornerDownLeft, HelpCircle } from "lucide-react";

interface ClarificationFormProps {
  text: string;
  onSubmit: (answersText: string) => void;
  onCancel: () => void;
}

export default function ClarificationForm({
  text,
  onSubmit,
  onCancel,
}: ClarificationFormProps) {
  const [answers, setAnswers] = useState<Record<string, string>>({});

  // Parse questions from bullet points in raw response
  const questions = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("•") || line.startsWith("?") || line.startsWith(""))
    .map((line) => line.replace(/^[•?\s]+/, "").trim());

  useEffect(() => {
    // Reset answers when questions change
    const initialAnswers: Record<string, string> = {};
    questions.forEach((q) => {
      initialAnswers[q] = "";
    });
    setAnswers(initialAnswers);
  }, [text]);

  const handleInputChange = (question: string, value: string) => {
    setAnswers((prev) => ({
      ...prev,
      [question]: value,
    }));
  };

  const isComplete = Object.values(answers).some((val) => val.trim() !== "");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!isComplete) return;

    // Combine answers into a clean follow-up sentence
    const combined = Object.entries(answers)
      .filter(([_, val]) => val.trim() !== "")
      .map(([q, val]) => {
        // Extract key term (e.g. "budget" from "What is your budget?")
        const lowerQ = q.toLowerCase();
        let key = "detail";
        if (lowerQ.includes("budget")) key = "Budget";
        else if (lowerQ.includes("brand")) key = "Preferred brand";
        else if (lowerQ.includes("size")) key = "Size";
        else if (lowerQ.includes("date") || lowerQ.includes("when")) key = "Date/Time";
        else if (lowerQ.includes("destination") || lowerQ.includes("where")) key = "Destination";
        else if (lowerQ.includes("food") || lowerQ.includes("restaurant")) key = "Food preference";
        else if (lowerQ.includes("use") || lowerQ.includes("purpose")) key = "Primary use";
        return `${key}: ${val.trim()}`;
      })
      .join(", ");

    onSubmit(combined);
  };

  if (questions.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="glass-panel border-primary/40 bg-primary/5 p-3.5 rounded-xl space-y-3"
    >
      <div className="flex items-center gap-2 text-primary">
        <HelpCircle size={14} className="animate-pulse" />
        <span className="font-display text-[9px] tracking-[0.2em] font-bold">REQUIRED PARAMETERS</span>
      </div>

      <form onSubmit={handleSubmit} className="space-y-2.5">
        <div className="max-h-[160px] overflow-y-auto pr-1 space-y-2 scrollbar-thin">
          {questions.map((q) => (
            <div key={q} className="space-y-1">
              <label className="text-[10px] font-body text-jarvis-bright leading-relaxed block">
                {q}
              </label>
              <input
                type="text"
                value={answers[q] || ""}
                onChange={(e) => handleInputChange(q, e.target.value)}
                placeholder="Specify details..."
                className="w-full bg-muted/40 border border-jarvis-border/30 rounded-lg px-3 py-1.5 text-xs text-foreground placeholder:text-jarvis-dim/40 font-body focus:outline-none focus:border-primary/60 transition-all"
              />
            </div>
          ))}
        </div>

        <div className="flex items-center justify-between pt-1">
          <button
            type="button"
            onClick={onCancel}
            className="text-[9px] text-jarvis-dim hover:text-rose-400 font-display tracking-widest transition-colors"
          >
            [ CANCEL ]
          </button>

          <button
            type="submit"
            disabled={!isComplete}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-primary/40 text-primary bg-primary/10 hover:bg-primary/20 disabled:opacity-40 disabled:cursor-not-allowed font-display text-[9px] tracking-widest transition-all shadow-[0_0_8px_rgba(0,170,255,0.2)]"
          >
            PROCEED <ArrowRight size={10} />
          </button>
        </div>
      </form>
    </motion.div>
  );
}
