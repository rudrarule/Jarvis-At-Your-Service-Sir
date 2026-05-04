import { useRef, useCallback, useEffect } from "react";

/**
 * useWakeWord — Web Speech API continuous listener.
 *
 * Listens passively for "Hey Jarvis" (case-insensitive).
 * Auto-restarts when recognition naturally ends.
 */
export function useWakeWord(onWake: () => void) {
  const recognitionRef = useRef<any>(null);
  const activeRef = useRef(false);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const onWakeRef = useRef(onWake);
  const commandModeRef = useRef<{ resolve: (text: string) => void } | null>(null);

  // Keep callback ref fresh
  useEffect(() => {
    onWakeRef.current = onWake;
  }, [onWake]);

  const WAKE_PHRASE = "hey jarvis";

  const startRecognition = useCallback(() => {
    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      console.error("Wake word: Speech Recognition not supported");
      return;
    }

    // Clean up any existing instance
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch { /* ignore */ }
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event: any) => {
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcriptRaw = result[0].transcript;
        const transcriptLower = transcriptRaw.toLowerCase().trim();

        if (commandModeRef.current) {
          // If we are explicitly listening for a command (e.g. after "Yes, sir?")
          if (result.isFinal) {
            const resolve = commandModeRef.current.resolve;
            commandModeRef.current = null; // Reset back to wake mode
            resolve(transcriptRaw.trim());
          }
        } else {
          // Wake word detection mode
          const matchIndex = transcriptLower.indexOf(WAKE_PHRASE);
          if (matchIndex !== -1) {
            const inlineCommand = transcriptRaw.substring(matchIndex + WAKE_PHRASE.length).trim();
            
            if (inlineCommand.length > 0 && result.isFinal) {
              console.log('🗣️ Wake word + inline command detected:', inlineCommand);
              onWakeRef.current(inlineCommand);
              return;
            } else if (!inlineCommand) {
              console.log('🗣️ Wake word detected: "Hey Jarvis"');
              onWakeRef.current();
              return;
            }
          }
        }
      }
    };

    recognition.onerror = (event: any) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      console.error("Wake word recognition error:", event.error);
    };

    recognition.onend = () => {
      // Auto-restart if still active
      if (activeRef.current) {
        restartTimerRef.current = setTimeout(() => {
          if (activeRef.current) {
            startRecognition();
          }
        }, 300);
      }
    };

    recognitionRef.current = recognition;
    try {
      recognition.start();
    } catch {
      // May fail if already started — retry after delay
      setTimeout(() => {
        if (activeRef.current) startRecognition();
      }, 500);
    }
  }, []);

  const start = useCallback(() => {
    if (activeRef.current) return;
    activeRef.current = true;
    startRecognition();
    console.log('👂 Wake word listening started (say "Hey Jarvis")');
  }, [startRecognition]);

  const stop = useCallback(() => {
    if (!activeRef.current) return; // prevent double-stop logs
    activeRef.current = false;
    clearTimeout(restartTimerRef.current);

    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch { /* ignore */ }
      recognitionRef.current = null;
    }
    console.log("👂 Wake word listening stopped");
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      activeRef.current = false;
      clearTimeout(restartTimerRef.current);
      try { recognitionRef.current?.abort(); } catch { /* ignore */ }
    };
  }, []);

  const listenOnce = useCallback((): Promise<string> => {
    return new Promise((resolve) => {
      commandModeRef.current = { resolve };
      console.log("👂 Wake system listening for follow-up command...");
      
      // Optional timeout to prevent getting stuck in command mode
      setTimeout(() => {
        if (commandModeRef.current) {
          commandModeRef.current = null;
          resolve(""); // Resolve empty to indicate timeout
        }
      }, 10000); // 10 seconds max wait
    });
  }, []);

  return { start, stop, listenOnce };
}
