import { useState, useCallback, useRef, useEffect } from "react";
import { useWakeWord } from "./useWakeWord";

const BACKEND_URL = "http://localhost:8002";

/**
 * Play a cinematic startup chime using the Web Audio API.
 */
function playStartupChime() {
  const AudioContext = window.AudioContext || (window as any).webkitAudioContext;
  if (!AudioContext) return;
  
  const ctx = new AudioContext();
  
  const playTone = (freq: number, time: number, type: OscillatorType) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    
    gain.gain.setValueAtTime(0, ctx.currentTime);
    gain.gain.linearRampToValueAtTime(0.3, ctx.currentTime + 0.1);
    gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + time);
    
    osc.connect(gain);
    gain.connect(ctx.destination);
    
    osc.start();
    osc.stop(ctx.currentTime + time);
  };

  // High-tech chord progression
  playTone(880, 0.5, 'sine');
  setTimeout(() => playTone(1108.73, 0.8, 'sine'), 100);
  setTimeout(() => playTone(1318.51, 1.2, 'sine'), 200);
}

/**
 * Speak text using ElevenLabs backend TTS (with browser fallback).
 * Returns a Promise that resolves when the speech finishes.
 */
async function speakWithPromise(text: string): Promise<void> {
  try {
    const res = await fetch(`${BACKEND_URL}/tts`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });

    if (res.ok && res.headers.get("content-type")?.includes("audio")) {
      const audioBlob = await res.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      
      return new Promise((resolve) => {
        const audio = new Audio(audioUrl);
        audio.onended = () => {
          URL.revokeObjectURL(audioUrl);
          resolve();
        };
        audio.onerror = () => {
          URL.revokeObjectURL(audioUrl);
          resolve();
        };
        audio.play().catch((err) => {
          console.warn("Audio play failed", err);
          resolve();
        });
      });
    }
  } catch (err) {
    console.warn("ElevenLabs TTS failed, using browser fallback:", err);
  }

  // Fallback: browser built-in TTS
  return new Promise((resolve) => {
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.rate = 1.0;
    utterance.pitch = 1.0;

    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();

    window.speechSynthesis.speak(utterance);

    // Safety timeout
    setTimeout(resolve, 10000);
  });
}

/**
 * useJarvisWake — Master controller for voice activation.
 *
 * Uses wake word detection ("Hey Jarvis").
 * Triggers the Stark Protocol orchestration macro.
 */
export function useJarvisWake(
  toggleListening: () => void,
  isListening: boolean,
  onBriefingReady?: (text: string) => void
) {
  const [isWakeActive, setIsWakeActive] = useState(false);
  const [isBooting, setIsBooting] = useState(false);
  const [isListeningMusic, setIsListeningMusic] = useState(false);
  const cooldownRef = useRef(false);
  const toggleListeningRef = useRef(toggleListening);
  const isListeningRef = useRef(isListening);

  useEffect(() => {
    toggleListeningRef.current = toggleListening;
  }, [toggleListening]);

  useEffect(() => {
    isListeningRef.current = isListening;
  }, [isListening]);

  // When main listening stops → restart wake word detection
  const prevListeningRef = useRef(false);
  useEffect(() => {
    if (prevListeningRef.current && !isListening) {
      // Main speech recognition just ended — safe to restart wake word
      console.log("🔄 Main listening ended, restarting wake word detector");
      setTimeout(() => {
        wakeRef.current.start();
      }, 500);
    }
    prevListeningRef.current = isListening;
  }, [isListening]);

  const wakeRef = useRef<{ start: () => void; stop: () => void }>({
    start: () => {},
    stop: () => {},
  });

  /** Stark Protocol Orchestration Handler */
  const handleActivation = useCallback(async () => {
    if (cooldownRef.current) return;
    cooldownRef.current = true;

    console.log("🚀 Stark Protocol Initiated!");

    // Stop wake detector
    wakeRef.current.stop();

    // 1. Play startup chime
    playStartupChime();

    // 2. Trigger UI Booting Animation
    setIsBooting(true);

    try {
      // 3. Fetch sequential briefing from backend
      const res = await fetch(`${BACKEND_URL}/stark-protocol/briefing`);
      const data = await res.json();
      
      // Stop the rapid pulsing just before speaking
      setIsBooting(false);

      if (onBriefingReady) {
        onBriefingReady(data.display_text || data.text);
      }

      // 4. Speak Briefing
      console.log("Speaking briefing...");
      await speakWithPromise(data.spoken_text || data.text);
      console.log("✅ Briefing finished");

      // 5. Speak final prompt
      await speakWithPromise("Would you like me to play your song, sir? It may help you relax during your coding session.");

      // Custom short-window listener for confirmation
      const listenForConfirmation = async (): Promise<string | null> => {
        return new Promise((resolve) => {
          const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
          if (!SpeechRecognition) return resolve(null);
          
          const recognition = new SpeechRecognition();
          recognition.lang = "en-US";
          recognition.interimResults = false;
          
          let timeoutId = setTimeout(() => {
            recognition.stop();
            resolve(null);
          }, 7000); // 7 second window

          recognition.onresult = (event: any) => {
            clearTimeout(timeoutId);
            resolve(event.results[0][0].transcript);
          };
          recognition.onerror = () => {
            clearTimeout(timeoutId);
            resolve(null);
          };
          recognition.onend = () => {
            clearTimeout(timeoutId);
            resolve(null);
          };

          setIsListeningMusic(true);
          recognition.start();
        }).finally(() => {
          setIsListeningMusic(false);
        }) as Promise<string | null>;
      };

      const askForMusic = async (attempt: number): Promise<void> => {
        const transcript = await listenForConfirmation();
        if (transcript) {
          const text = transcript.toLowerCase();
          const isPositive = /yes|play it|go ahead|sure|yes please|yeah|yep|do it/i.test(text);
          const isNegative = /no|skip|not now|maybe later|nope|stop|cancel/i.test(text);
          
          if (isPositive) {
            await speakWithPromise("Certainly, sir. Playing Lose My Mind.");
            try {
              await fetch(`${BACKEND_URL}/stark-protocol/music`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ query: "Lose My Mind F1" })
              });
            } catch (err) {
              console.error("Music tool failed:", err);
            }
          } else if (isNegative) {
            await speakWithPromise("Understood, sir.");
          } else {
            await speakWithPromise("Understood, sir.");
          }
        } else {
          if (attempt === 1) {
            await speakWithPromise("I did not catch that, sir. Would you like me to play your song?");
            await askForMusic(2);
          } else {
            console.log("Canceling music offer due to no response.");
          }
        }
      };

      await askForMusic(1);
      
    } catch (err) {
      console.error("Stark Protocol failed:", err);
      setIsBooting(false);
      await speakWithPromise("Systems online, sir. How may I assist?");
    }

    // After activation sequence finishes, cooldown rests.
    setTimeout(() => {
      cooldownRef.current = false;
      console.log("🔄 Wake cooldown finished, restarting wake word detector");
      wakeRef.current.start();
    }, 1000);
  }, []);

  const wakeWord = useWakeWord(handleActivation);

  useEffect(() => {
    wakeRef.current = wakeWord;
  }, [wakeWord]);

  const startWakeSystem = useCallback(() => {
    console.log("🟢 Wake system starting...");
    wakeWord.start();
    setIsWakeActive(true);
  }, [wakeWord]);

  const stopWakeSystem = useCallback(() => {
    console.log("🔴 Wake system stopped");
    wakeWord.stop();
    setIsWakeActive(false);
  }, [wakeWord]);

  return {
    isWakeActive,
    isBooting,
    isListeningMusic,
    startWakeSystem,
    stopWakeSystem,
    triggerStarkProtocol: handleActivation,
  };
}
