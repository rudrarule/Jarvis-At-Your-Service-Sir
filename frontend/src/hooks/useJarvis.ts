import { useState, useCallback, useRef } from "react";

export interface Message {
  id: number;
  text: string;
  sender: "user" | "jarvis";
}

const BACKEND_URL = "http://localhost:8002";

/**
 * useJarvis — manages the full AI pipeline:
 *   speech recognition → backend calls → chat history → TTS (ElevenLabs or browser)
 */
export function useJarvis() {
  const [isListening, setIsListening] = useState(false);
  const [isResponding, setIsResponding] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [messages, setMessages] = useState<Message[]>([
    { id: 1, text: "System initialized. All modules online.", sender: "jarvis" },
  ]);
  const recognitionRef = useRef<any>(null);

  /** Text-to-Speech: try ElevenLabs first, fall back to browser TTS */
  const speak = useCallback(async (text: string) => {
    try {
      // Try ElevenLabs via backend
      const res = await fetch(`${BACKEND_URL}/tts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });

      if (res.ok && res.headers.get("content-type")?.includes("audio")) {
        // ElevenLabs returned audio — play it
        const audioBlob = await res.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        const audio = new Audio(audioUrl);
        audio.onended = () => URL.revokeObjectURL(audioUrl);
        audio.play();
        return;
      }
    } catch (err) {
      console.warn("ElevenLabs TTS failed, using browser fallback:", err);
    }

    // Fallback: browser built-in TTS
    const speech = new SpeechSynthesisUtterance(text);
    speech.lang = "en-US";
    window.speechSynthesis.speak(speech);
  }, []);

  /** Send a message (voice or typed) to the backend and handle the response */
  const sendToJarvis = useCallback(
    async (message: string) => {
      // Add user message to chat history
      setMessages((prev) => [
        ...prev,
        { id: Date.now(), text: message, sender: "user" },
      ]);

      setIsResponding(true);
      // UX Enhancement: Provide instant audio & visual feedback
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, text: "Certainly, sir. Give me a moment.", sender: "jarvis" },
      ]);
      speak("Certainly, sir. Give me a moment.");
      
      try {
        const res = await fetch(`${BACKEND_URL}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message }),
        });
        const data = await res.json();
        const reply = data.reply ?? "No response received.";

        // Add J.A.R.V.I.S reply to chat history
        setMessages((prev) => [
          ...prev,
          { id: Date.now() + 1, text: reply, sender: "jarvis" },
        ]);

        // Speak the reply aloud (ElevenLabs or browser fallback)
        speak(reply);
      } catch (err) {
        console.error("Failed to reach J.A.R.V.I.S backend:", err);
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now() + 1,
            text: "Connection to backend lost. Please check the server.",
            sender: "jarvis",
          },
        ]);
      } finally {
        setIsResponding(false);
      }
    },
    [speak]
  );

  /** Start / stop browser speech recognition */
  const toggleListening = useCallback(() => {
    // Stop if currently listening
    if (isListening && recognitionRef.current) {
      recognitionRef.current.stop();
      recognitionRef.current = null;
      setIsListening(false);
      return;
    }

    const SpeechRecognition =
      (window as any).SpeechRecognition ||
      (window as any).webkitSpeechRecognition;

    if (!SpeechRecognition) {
      console.error("Speech Recognition not supported in this browser.");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;

    recognition.onresult = (event: any) => {
      const text = event.results[0][0].transcript;
      setTranscript(text);
      sendToJarvis(text);
    };

    recognition.onerror = (event: any) => {
      console.error("Speech recognition error:", event.error);
      setIsListening(false);
      recognitionRef.current = null;
    };

    recognition.onend = () => {
      setIsListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, [isListening, sendToJarvis]);

  /** Send a typed message (used by ChatPanel input) */
  const sendMessage = useCallback(
    (text: string) => {
      if (!text.trim()) return;
      sendToJarvis(text);
    },
    [sendToJarvis]
  );

  return {
    isListening,
    isResponding,
    transcript,
    messages,
    toggleListening,
    sendMessage,
  };
}
