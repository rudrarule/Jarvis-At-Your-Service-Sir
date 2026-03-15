import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Sphere, MeshDistortMaterial } from "@react-three/drei";
import * as THREE from "three";

interface AICoreOrbProps {
  isListening: boolean;
  isResponding: boolean;
}

function CoreOrb({ isListening, isResponding }: AICoreOrbProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const glowRef = useRef<THREE.Mesh>(null);
  const ringRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (meshRef.current) {
      meshRef.current.rotation.y = t * 0.3;
      meshRef.current.rotation.x = Math.sin(t * 0.2) * 0.1;
      const baseScale = isListening ? 1.15 : isResponding ? 1.08 : 1;
      const breathe = Math.sin(t * 1.5) * 0.03;
      const s = baseScale + breathe;
      meshRef.current.scale.set(s, s, s);
    }
    if (glowRef.current) {
      const glowScale = 1.4 + Math.sin(t * 2) * 0.08;
      glowRef.current.scale.set(glowScale, glowScale, glowScale);
      (glowRef.current.material as THREE.MeshBasicMaterial).opacity =
        0.08 + Math.sin(t * 3) * 0.04 + (isResponding ? 0.06 : 0);
    }
    if (ringRef.current) {
      ringRef.current.rotation.z = t * 0.5;
      ringRef.current.rotation.x = Math.PI / 2 + Math.sin(t * 0.3) * 0.2;
    }
  });

  return (
    <group>
      {/* Outer glow */}
      <Sphere ref={glowRef} args={[1.4, 32, 32]}>
        <meshBasicMaterial
          color="#0088ff"
          transparent
          opacity={0.08}
          side={THREE.BackSide}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </Sphere>

      {/* Main orb */}
      <Sphere ref={meshRef} args={[1, 64, 64]}>
        <MeshDistortMaterial
          color="#0066cc"
          emissive="#0099ff"
          emissiveIntensity={isResponding ? 1.2 : 0.6}
          roughness={0.2}
          metalness={0.8}
          distort={isListening ? 0.4 : 0.2}
          speed={isListening ? 4 : 2}
          transparent
          opacity={0.9}
        />
      </Sphere>

      {/* Inner core */}
      <Sphere args={[0.5, 32, 32]}>
        <meshBasicMaterial
          color="#00ccff"
          transparent
          opacity={0.4}
          blending={THREE.AdditiveBlending}
        />
      </Sphere>

      {/* Ring */}
      <mesh ref={ringRef}>
        <torusGeometry args={[1.6, 0.02, 16, 100]} />
        <meshBasicMaterial
          color="#00aaff"
          transparent
          opacity={0.5}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      {/* Second ring */}
      <mesh rotation={[Math.PI / 3, 0, 0]}>
        <torusGeometry args={[1.8, 0.015, 16, 100]} />
        <meshBasicMaterial
          color="#00ccff"
          transparent
          opacity={0.3}
          blending={THREE.AdditiveBlending}
        />
      </mesh>

      <pointLight color="#0088ff" intensity={2} distance={10} />
    </group>
  );
}

export default function AICore({
  isListening,
  isResponding,
}: AICoreOrbProps) {
  return (
    <div className="relative w-[320px] h-[320px] md:w-[400px] md:h-[400px]">
      <Canvas camera={{ position: [0, 0, 5], fov: 45 }} gl={{ alpha: true }}>
        <ambientLight intensity={0.3} />
        <directionalLight position={[5, 5, 5]} intensity={0.5} />
        <CoreOrb isListening={isListening} isResponding={isResponding} />
      </Canvas>
      {/* CSS glow behind */}
      <div
        className="absolute inset-0 -z-10 rounded-full opacity-40 blur-3xl"
        style={{ background: "radial-gradient(circle, hsl(200 100% 50% / 0.4), transparent 70%)" }}
      />
    </div>
  );
}
