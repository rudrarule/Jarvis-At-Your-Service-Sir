import { useState, useCallback, useRef, useEffect } from "react";
import { useWakeWord } from "./useWakeWord";

/**
 * Speak text using browser SpeechSynthesis.
 * Returns a Promise that resolves when the speech finishes.
 */
function speakGreeting(text: string): Promise<void> {
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
 * When activated → speaks greeting → waits → starts speech recognition.
 */
export function useJarvisWake(
  toggleListening: () => void,
  isListening: boolean
) {
  const [isWakeActive, setIsWakeActive] = useState(false);
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

  const GREETING = "Greetings sir, how may I help you?";

  /** Core activation handler */
  const handleActivation = useCallback(async () => {
    if (cooldownRef.current) return;
    cooldownRef.current = true;

    console.log("🚀 Jarvis activated!");

    // Stop wake detector
    wakeRef.current.stop();

    // Speak greeting and wait
    await speakGreeting(GREETING);
    console.log("✅ Greeting finished");

    // Small delay, then start main speech recognition
    await new Promise((r) => setTimeout(r, 300));
    toggleListeningRef.current();

    // After activation, coodlown rests.
    // Wake word will restart when main listening ends (via the useEffect above).
    setTimeout(() => {
      cooldownRef.current = false;
      console.log("🔄 Wake cooldown finished (wake word waits for mic release)");
    }, 3000);
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
    startWakeSystem,
    stopWakeSystem,
  };
}

