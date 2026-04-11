import { useRef, useEffect } from "react";
import { motion } from "framer-motion";

interface AICoreProps {
  isListening: boolean;
  isResponding: boolean;
}

export default function AICore({ isListening, isResponding }: AICoreProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const size = 320;
    canvas.width = size;
    canvas.height = size;
    const cx = size / 2;
    const cy = size / 2;
    let animId: number;
    let time = 0;

    const animate = () => {
      time += 0.016;
      ctx.clearRect(0, 0, size, size);

      // Outer glow
      const glowGrad = ctx.createRadialGradient(cx, cy, 60, cx, cy, 150);
      glowGrad.addColorStop(0, `rgba(0, 136, 255, ${isResponding ? 0.15 : 0.08})`);
      glowGrad.addColorStop(1, "transparent");
      ctx.fillStyle = glowGrad;
      ctx.fillRect(0, 0, size, size);

      // Rings: Speed up rotation when thinking for a high-energy look
      const drawRing = (radius: number, opacity: number, speed: number) => {
        ctx.save();
        ctx.translate(cx, cy);
        // Multiply by 2.5 to make it spin rapidly when processing
        const currentSpeed = isResponding ? speed * 2.5 : speed;
        ctx.rotate(time * currentSpeed);
        ctx.beginPath();
        ctx.ellipse(0, 0, radius, radius * 0.4, Math.sin(time * 0.3) * 0.3, 0, Math.PI * 2);
        
        // Shift ring color to purple/pink when thinking
        ctx.strokeStyle = isResponding 
          ? `rgba(180, 50, 255, ${opacity * 1.5})` 
          : `rgba(0, 170, 255, ${opacity})`;
          
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.restore();
      };
      drawRing(100, 0.4, 0.5);
      drawRing(115, 0.25, -0.3);

      // Main sphere
      const baseRadius = 65;
      const breathe = Math.sin(time * 1.5) * 3;
      const scaleBonus = isListening ? 8 : isResponding ? 4 : 0;
      const radius = baseRadius + breathe + scaleBonus;

      const sphereGrad = ctx.createRadialGradient(cx - 15, cy - 15, 10, cx, cy, radius);
      
      if (isResponding) {
        sphereGrad.addColorStop(0, "rgba(200, 100, 255, 0.9)");
        sphereGrad.addColorStop(0.5, "rgba(100, 50, 204, 0.8)");
        sphereGrad.addColorStop(1, "rgba(50, 0, 150, 0.3)");
        ctx.shadowColor = `rgba(160, 50, 255, 0.9)`;
      } else {
        sphereGrad.addColorStop(0, "rgba(0, 200, 255, 0.9)");
        sphereGrad.addColorStop(0.5, "rgba(0, 100, 204, 0.8)");
        sphereGrad.addColorStop(1, "rgba(0, 50, 150, 0.3)");
        ctx.shadowColor = `rgba(0, 136, 255, ${isResponding ? 0.8 : 0.5})`;
      }

      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fillStyle = sphereGrad;
      ctx.shadowBlur = isResponding ? 60 : 40;
      ctx.fill();

      // Inner core
      const innerGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 30);
      innerGrad.addColorStop(0, `rgba(0, 220, 255, ${0.6 + Math.sin(time * 3) * 0.2})`);
      innerGrad.addColorStop(1, "transparent");
      ctx.beginPath();
      ctx.arc(cx, cy, 30, 0, Math.PI * 2);
      ctx.fillStyle = innerGrad;
      ctx.shadowBlur = 20;
      ctx.shadowColor = "rgba(0, 220, 255, 0.6)";
      ctx.fill();
      ctx.shadowBlur = 0;

      // Energy lines on sphere surface
      for (let i = 0; i < 6; i++) {
        const angle = (i / 6) * Math.PI * 2 + time * 0.8;
        const x1 = cx + Math.cos(angle) * radius * 0.6;
        const y1 = cy + Math.sin(angle) * radius * 0.6;
        const x2 = cx + Math.cos(angle + 0.5) * radius * 0.9;
        const y2 = cy + Math.sin(angle + 0.5) * radius * 0.9;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.strokeStyle = `rgba(0, 200, 255, ${0.2 + Math.sin(time * 2 + i) * 0.15})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      animId = requestAnimationFrame(animate);
    };

    animate();
    return () => cancelAnimationFrame(animId);
  }, [isListening, isResponding]);

  return (
    <motion.div
      className="relative"
      animate={{ scale: isListening ? 1.05 : 1 }}
      transition={{ type: "spring", stiffness: 200, damping: 20 }}
    >
      <canvas
        ref={canvasRef}
        className="w-[280px] h-[280px] md:w-[320px] md:h-[320px]"
      />
      {/* CSS glow behind */}
      <div
        className="absolute inset-0 -z-10 rounded-full opacity-40 blur-3xl"
        style={{
          background: "radial-gradient(circle, hsl(200 100% 50% / 0.4), transparent 70%)",
        }}
      />
    </motion.div>
  );
}
