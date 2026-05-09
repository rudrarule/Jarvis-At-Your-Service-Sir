import { useRef, useCallback, useEffect } from "react";
import * as ort from "onnxruntime-web";

/**
 * useWakeWord — Local neural wake word detection via OpenWakeWord + ONNX Runtime.
 *
 * Runs entirely in the browser (WASM). No API keys, no cloud, no network.
 * Detects "Hey Jarvis" using the OpenWakeWord hey_jarvis_v0.1 model.
 *
 * Pipeline (per 80ms chunk):
 *   1. Silero VAD   → is speech active?
 *   2. Mel spectrogram → 5 mel frames (32 features each)
 *   3. Embedding model → 96-dim embedding (from 76 accumulated mel frames)
 *   4. Keyword head   → score 0-1 (from N accumulated embeddings)
 *   5. If score > threshold AND speech active → fire onWake()
 *
 * Falls back to webkitSpeechRecognition if ONNX fails to load.
 */

const MODEL_BASE = "/openwakeword/models";
const SAMPLE_RATE = 16000;
const FRAME_SIZE = 1280; // 80ms at 16kHz
const DETECTION_THRESHOLD = 0.5;
const COOLDOWN_MS = 2500;
const VAD_HANGOVER_FRAMES = 12;

// ── ONNX Sessions (module-level singletons) ────────────────────
let melSession: ort.InferenceSession | null = null;
let embSession: ort.InferenceSession | null = null;
let vadSession: ort.InferenceSession | null = null;
let kwSession: ort.InferenceSession | null = null;
let kwWindowSize = 16; // will be inferred from model
let modelsLoaded = false;
let modelsLoading = false;
let modelLoadError = false;

// Model input/output name caches
let melInputName = "";
let melOutputName = "";
let embInputName = "";
let embOutputName = "";
let kwInputName = "";
let kwOutputName = "";

async function loadModels(): Promise<boolean> {
  if (modelsLoaded) return true;
  if (modelLoadError) return false;
  if (modelsLoading) {
    while (modelsLoading) await new Promise((r) => setTimeout(r, 100));
    return modelsLoaded;
  }

  modelsLoading = true;
  try {
    ort.env.wasm.numThreads = 1;
    ort.env.wasm.simd = true;
    ort.env.wasm.wasmPaths = "/openwakeword/ort/";

    console.log("[OWW] Loading ONNX models...");
    const opts = { executionProviders: ["wasm"] as const };

    const [mel, emb, vad, kw] = await Promise.all([
      ort.InferenceSession.create(`${MODEL_BASE}/melspectrogram.onnx`, opts),
      ort.InferenceSession.create(`${MODEL_BASE}/embedding_model.onnx`, opts),
      ort.InferenceSession.create(`${MODEL_BASE}/silero_vad.onnx`, opts),
      ort.InferenceSession.create(`${MODEL_BASE}/hey_jarvis_v0.1.onnx`, opts),
    ]);

    melSession = mel;
    embSession = emb;
    vadSession = vad;
    kwSession = kw;

    // Cache input/output names
    melInputName = mel.inputNames[0];
    melOutputName = mel.outputNames[0];
    embInputName = emb.inputNames[0];
    embOutputName = emb.outputNames[0];
    kwInputName = kw.inputNames[0];
    kwOutputName = kw.outputNames[0];

    // Infer keyword window size from model metadata if possible
    // Default to 16 if we can't determine it
    kwWindowSize = 16;

    modelsLoaded = true;
    console.log("[OWW] ✅ All models loaded. Local listener online.");
    return true;
  } catch (err) {
    console.error("[OWW] ❌ Failed to load ONNX models:", err);
    modelLoadError = true;
    return false;
  } finally {
    modelsLoading = false;
  }
}

// ── Pipeline State (reset per start) ────────────────────────
interface PipelineState {
  melBuffer: Float32Array[];
  embeddingHistory: Float32Array[];
  vadH: ort.Tensor;
  vadC: ort.Tensor;
  isSpeechActive: boolean;
  vadHangover: number;
  isCoolingDown: boolean;
}

function createPipelineState(): PipelineState {
  return {
    melBuffer: [],
    embeddingHistory: Array.from({ length: kwWindowSize }, () => new Float32Array(96).fill(0)),
    vadH: new ort.Tensor("float32", new Float32Array(128).fill(0), [2, 1, 64]),
    vadC: new ort.Tensor("float32", new Float32Array(128).fill(0), [2, 1, 64]),
    isSpeechActive: false,
    vadHangover: 0,
    isCoolingDown: false,
  };
}

async function runVad(chunk: Float32Array, state: PipelineState): Promise<boolean> {
  if (!vadSession) return false;
  try {
    const input = new ort.Tensor("float32", chunk, [1, chunk.length]);
    const sr = new ort.Tensor("int64", BigInt64Array.from([BigInt(SAMPLE_RATE)]), []);
    const result = await vadSession.run({ input, sr, h: state.vadH, c: state.vadC });
    state.vadH = result.hn as ort.Tensor;
    state.vadC = result.cn as ort.Tensor;
    const confidence = (result.output as ort.Tensor).data[0] as number;
    return confidence > 0.5;
  } catch {
    return false;
  }
}

async function runInference(
  chunk: Float32Array,
  state: PipelineState,
  onDetect: () => void
): Promise<void> {
  if (!melSession || !embSession || !kwSession) return;

  try {
    // Step 1: Mel spectrogram — produces 5 mel frames of 32 features each
    const melInput = new ort.Tensor("float32", chunk, [1, FRAME_SIZE]);
    const melResult = await melSession.run({ [melInputName]: melInput });
    const melData = (melResult[melOutputName] as ort.Tensor).data as Float32Array;

    // Normalize mel output (matches reference implementation)
    const normalizedMel = new Float32Array(melData.length);
    for (let i = 0; i < melData.length; i++) {
      normalizedMel[i] = melData[i] / 10.0 + 2.0;
    }

    // Split into 5 frames of 32 features and push to buffer
    for (let j = 0; j < 5; j++) {
      state.melBuffer.push(new Float32Array(normalizedMel.subarray(j * 32, (j + 1) * 32)));
    }

    // Step 2: When we have 76+ mel frames, compute embedding
    while (state.melBuffer.length >= 76) {
      const windowFrames = state.melBuffer.slice(0, 76);
      const flatMel = new Float32Array(76 * 32);
      for (let j = 0; j < windowFrames.length; j++) {
        flatMel.set(windowFrames[j], j * 32);
      }

      // Embedding model expects [1, 76, 32, 1]
      const embInput = new ort.Tensor("float32", flatMel, [1, 76, 32, 1]);
      const embResult = await embSession.run({ [embInputName]: embInput });
      const embData = (embResult[embOutputName] as ort.Tensor).data as Float32Array;
      const embVector = new Float32Array(embData);

      // Step 3: Update embedding history and run keyword model
      state.embeddingHistory.shift();
      state.embeddingHistory.push(embVector);

      const flatEmb = new Float32Array(kwWindowSize * 96);
      for (let j = 0; j < state.embeddingHistory.length; j++) {
        flatEmb.set(state.embeddingHistory[j], j * 96);
      }

      const kwInput = new ort.Tensor("float32", flatEmb, [1, kwWindowSize, 96]);
      const kwResult = await kwSession.run({ [kwInputName]: kwInput });
      const score = (kwResult[kwOutputName] as ort.Tensor).data[0] as number;

      // Step 4: Emit detection if score > threshold AND speech is active
      if (
        score > DETECTION_THRESHOLD &&
        state.isSpeechActive &&
        !state.isCoolingDown
      ) {
        console.log(`[OWW] 🎯 Hotword detected! (score: ${score.toFixed(3)})`);
        state.isCoolingDown = true;
        setTimeout(() => { state.isCoolingDown = false; }, COOLDOWN_MS);
        onDetect();
      }

      // Slide mel buffer by 8 frames (overlapping window)
      state.melBuffer.splice(0, 8);
    }
  } catch (err) {
    // Silently swallow inference errors — don't crash the pipeline
    console.error("[OWW] Inference error:", err);
  }
}

async function processChunk(
  chunk: Float32Array,
  state: PipelineState,
  onDetect: () => void
): Promise<void> {
  // Run VAD
  const vadTriggered = await runVad(chunk, state);

  if (vadTriggered) {
    state.isSpeechActive = true;
    state.vadHangover = VAD_HANGOVER_FRAMES;
  } else if (state.isSpeechActive) {
    state.vadHangover -= 1;
    if (state.vadHangover <= 0) {
      state.isSpeechActive = false;
    }
  }

  // Run mel → embedding → keyword pipeline
  await runInference(chunk, state, onDetect);
}

// ── Fallback: webkitSpeechRecognition ──────────────────────────
function createFallbackRecognition(
  onWakeRef: React.MutableRefObject<(inlineCommand?: string) => void>,
  commandModeRef: React.MutableRefObject<{ resolve: (text: string) => void } | null>,
  activeRef: React.MutableRefObject<boolean>,
  restartTimerRef: React.MutableRefObject<ReturnType<typeof setTimeout> | undefined>,
  startFallback: () => void
) {
  const SpeechRecognition =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
  if (!SpeechRecognition) return null;

  const recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.continuous = true;
  recognition.interimResults = true;

  const WAKE_PHRASE = "hey jarvis";

  recognition.onresult = (event: any) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      const transcriptRaw = result[0].transcript;
      const transcriptLower = transcriptRaw.toLowerCase().trim();

      if (commandModeRef.current) {
        if (result.isFinal) {
          const resolve = commandModeRef.current.resolve;
          commandModeRef.current = null;
          resolve(transcriptRaw.trim());
        }
      } else {
        const matchIndex = transcriptLower.indexOf(WAKE_PHRASE);
        if (matchIndex !== -1) {
          const inlineCommand = transcriptRaw.substring(matchIndex + WAKE_PHRASE.length).trim();
          if (inlineCommand.length > 0 && result.isFinal) {
            onWakeRef.current(inlineCommand);
            return;
          } else if (!inlineCommand) {
            onWakeRef.current();
            return;
          }
        }
      }
    }
  };

  recognition.onerror = (event: any) => {
    if (event.error === "no-speech" || event.error === "aborted") return;
    console.error("[FALLBACK] Wake word recognition error:", event.error);
  };

  recognition.onend = () => {
    if (activeRef.current) {
      restartTimerRef.current = setTimeout(() => {
        if (activeRef.current) startFallback();
      }, 300);
    }
  };

  return recognition;
}

// ── Hook ───────────────────────────────────────────────────────
export function useWakeWord(onWake: (inlineCommand?: string) => void) {
  const activeRef = useRef(false);
  const restartTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const onWakeRef = useRef(onWake);
  const commandModeRef = useRef<{ resolve: (text: string) => void } | null>(null);

  // ONNX pipeline state
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workletNodeRef = useRef<AudioWorkletNode | null>(null);
  const pipelineStateRef = useRef<PipelineState | null>(null);
  const processingQueueRef = useRef<Promise<void>>(Promise.resolve());
  const usingFallbackRef = useRef(false);
  const fallbackRecognitionRef = useRef<any>(null);

  useEffect(() => { onWakeRef.current = onWake; }, [onWake]);

  // ── ONNX AudioWorklet-based mic processing ──────────────────
  const startOnnxListener = useCallback(async () => {
    if (!activeRef.current) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: SAMPLE_RATE, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      audioContextRef.current = audioContext;

      // Create AudioWorklet from inline processor
      const workletCode = `
class OWWProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = new Float32Array(${FRAME_SIZE});
    this._pos = 0;
  }
  process(inputs) {
    const input = inputs[0][0];
    if (input) {
      for (let i = 0; i < input.length; i++) {
        this._buffer[this._pos++] = input[i];
        if (this._pos === ${FRAME_SIZE}) {
          this.port.postMessage(this._buffer);
          this._pos = 0;
        }
      }
    }
    return true;
  }
}
registerProcessor('oww-processor', OWWProcessor);
`;
      const blob = new Blob([workletCode], { type: "application/javascript" });
      const workletURL = URL.createObjectURL(blob);
      await audioContext.audioWorklet.addModule(workletURL);
      URL.revokeObjectURL(workletURL);

      const workletNode = new AudioWorkletNode(audioContext, "oww-processor");
      workletNodeRef.current = workletNode;

      // Initialize pipeline state
      pipelineStateRef.current = createPipelineState();

      workletNode.port.onmessage = (event) => {
        const chunk = event.data as Float32Array;
        if (!chunk || !activeRef.current || commandModeRef.current) return;

        const state = pipelineStateRef.current;
        if (!state) return;

        // Queue processing to avoid overlapping inference
        processingQueueRef.current = processingQueueRef.current
          .then(() => processChunk(chunk, state, () => onWakeRef.current()))
          .catch((err) => console.error("[OWW] Pipeline error:", err));
      };

      const source = audioContext.createMediaStreamSource(stream);
      const gainNode = audioContext.createGain();
      gainNode.gain.value = 1.0;
      source.connect(gainNode);
      gainNode.connect(workletNode);
      workletNode.connect(audioContext.destination);

      console.log('[OWW] 👂 Local listener online. Say "Hey Jarvis"...');
    } catch (err) {
      console.error("[OWW] Microphone access failed:", err);
    }
  }, []);

  const stopOnnxListener = useCallback(() => {
    if (workletNodeRef.current) {
      workletNodeRef.current.port.onmessage = null;
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    if (audioContextRef.current && audioContextRef.current.state !== "closed") {
      audioContextRef.current.close().catch(() => {});
      audioContextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    pipelineStateRef.current = null;
  }, []);

  // ── Fallback methods ────────────────────────────────────────
  const startFallbackFn = useCallback(() => {
    if (!activeRef.current) return;
    if (fallbackRecognitionRef.current) {
      try { fallbackRecognitionRef.current.abort(); } catch { /* */ }
    }
    const recognition = createFallbackRecognition(
      onWakeRef, commandModeRef, activeRef, restartTimerRef, startFallbackFn
    );
    if (!recognition) return;
    fallbackRecognitionRef.current = recognition;
    try { recognition.start(); } catch {
      setTimeout(() => { if (activeRef.current) startFallbackFn(); }, 500);
    }
  }, []);

  // ── Public API ──────────────────────────────────────────────
  const start = useCallback(async () => {
    if (activeRef.current) return;
    activeRef.current = true;

    const onnxOk = await loadModels();
    if (onnxOk) {
      usingFallbackRef.current = false;
      startOnnxListener();
      console.log("[OWW] 🟢 Wake word listening started (ONNX local mode)");
    } else {
      console.warn("[OWW] ⚠️ Falling back to webkitSpeechRecognition (cloud-based)");
      usingFallbackRef.current = true;
      startFallbackFn();
      console.log('[FALLBACK] 👂 Wake word listening started (say "Hey Jarvis")');
    }
  }, [startOnnxListener, startFallbackFn]);

  const stop = useCallback(() => {
    if (!activeRef.current) return;
    activeRef.current = false;
    clearTimeout(restartTimerRef.current);

    if (usingFallbackRef.current) {
      if (fallbackRecognitionRef.current) {
        try { fallbackRecognitionRef.current.abort(); } catch { /* */ }
        fallbackRecognitionRef.current = null;
      }
    } else {
      stopOnnxListener();
    }
    console.log("👂 Wake word listening stopped");
  }, [stopOnnxListener]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      activeRef.current = false;
      clearTimeout(restartTimerRef.current);
      stopOnnxListener();
      try { fallbackRecognitionRef.current?.abort(); } catch { /* */ }
    };
  }, [stopOnnxListener]);

  /**
   * listenOnce — Command capture mode.
   *
   * FOREGROUND TAB: Uses browser SpeechRecognition (fast, low latency).
   * BACKGROUND TAB: Records mic audio → encodes WAV → POSTs to backend /stt for Whisper transcription.
   *
   * The ONNX AudioWorklet keeps running but pauses wake-word processing
   * via commandModeRef. This avoids the stop/restart cycle that breaks
   * on the second invocation.
   */
  const listenOnce = useCallback((): Promise<string> => {
    return new Promise(async (resolve) => {
      if (usingFallbackRef.current) {
        commandModeRef.current = { resolve };
        console.log("👂 [FALLBACK] Listening for follow-up command...");
        setTimeout(() => {
          if (commandModeRef.current) {
            commandModeRef.current = null;
            resolve("");
          }
        }, 10000);
        return;
      }

      // Pause ONNX wake detection (worklet keeps running, just skips processing)
      const dummyResolve = { resolve: (_s: string) => {} };
      commandModeRef.current = dummyResolve;
      console.log("👂 [OWW] ONNX paused via commandMode. Listening for command...");

      const resumeOnnx = () => {
        commandModeRef.current = null;
        console.log("[OWW] 👂 ONNX wake detection resumed.");
      };

      // ── BACKGROUND TAB: Record audio and send to backend STT ──
      if (document.hidden) {
        console.log("[OWW] 🔇 Tab in background — using backend STT for command capture");

        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
          });

          const audioContext = new AudioContext({ sampleRate: 16000 });
          const source = audioContext.createMediaStreamSource(stream);
          const processor = audioContext.createScriptProcessor(4096, 1, 1);
          const chunks: Float32Array[] = [];
          let recording = true;

          processor.onaudioprocess = (e) => {
            if (!recording) return;
            const data = e.inputBuffer.getChannelData(0);
            chunks.push(new Float32Array(data));
          };

          source.connect(processor);
          processor.connect(audioContext.destination);

          console.log("[OWW] 🎙️ Recording command (up to 8s)...");

          await new Promise<void>((r) => setTimeout(r, 8000));
          recording = false;

          // Cleanup recording mic (not the ONNX mic)
          processor.disconnect();
          source.disconnect();
          audioContext.close().catch(() => {});
          stream.getTracks().forEach((t) => t.stop());

          // Encode as WAV
          const totalSamples = chunks.reduce((a, c) => a + c.length, 0);
          if (totalSamples < 1600) {
            console.log("[OWW] Recording too short, skipping STT");
            resumeOnnx();
            resolve("");
            return;
          }

          const combined = new Float32Array(totalSamples);
          let offset = 0;
          for (const chunk of chunks) {
            combined.set(chunk, offset);
            offset += chunk.length;
          }

          // Float32 to Int16 PCM
          const pcm = new Int16Array(combined.length);
          for (let i = 0; i < combined.length; i++) {
            const s = Math.max(-1, Math.min(1, combined[i]));
            pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }

          // WAV header
          const wavBuffer = new ArrayBuffer(44 + pcm.length * 2);
          const view = new DataView(wavBuffer);
          const writeString = (o: number, s: string) => {
            for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i));
          };
          writeString(0, "RIFF");
          view.setUint32(4, 36 + pcm.length * 2, true);
          writeString(8, "WAVE");
          writeString(12, "fmt ");
          view.setUint32(16, 16, true);
          view.setUint16(20, 1, true);
          view.setUint16(22, 1, true);
          view.setUint32(24, 16000, true);
          view.setUint32(28, 32000, true);
          view.setUint16(32, 2, true);
          view.setUint16(34, 16, true);
          writeString(36, "data");
          view.setUint32(40, pcm.length * 2, true);
          new Int16Array(wavBuffer, 44).set(pcm);

          console.log(`[OWW] 📦 Sending ${(pcm.length / 16000).toFixed(1)}s audio to backend STT...`);

          const formData = new FormData();
          formData.append("audio", new Blob([wavBuffer], { type: "audio/wav" }), "command.wav");

          const res = await fetch("http://localhost:8082/stt", {
            method: "POST",
            body: formData,
          });

          const data = await res.json();
          const transcript = data.text?.trim() || "";

          if (transcript) {
            console.log(`[OWW] 📝 Backend STT result: "${transcript}"`);
          } else {
            console.log("[OWW] Backend STT returned empty");
          }

          resumeOnnx();
          resolve(transcript);
        } catch (err) {
          console.error("[OWW] Background STT failed:", err);
          resumeOnnx();
          resolve("");
        }
        return;
      }

      // ── FOREGROUND TAB: Use browser SpeechRecognition ──
      console.log("👂 [OWW] Listening for command via SpeechRecognition...");

      const SpeechRecognition =
        (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

      if (!SpeechRecognition) {
        resumeOnnx();
        resolve("");
        return;
      }

      const recognition = new SpeechRecognition();
      recognition.lang = "en-US";
      recognition.continuous = false;
      recognition.interimResults = false;
      let resolved = false;

      recognition.onresult = (event: any) => {
        if (resolved) return;
        const transcript = event.results[0]?.[0]?.transcript?.trim() || "";
        if (transcript) {
          resolved = true;
          recognition.stop();
          console.log(`[OWW] 📝 Command captured: "${transcript}"`);
          resumeOnnx();
          resolve(transcript);
        }
      };

      recognition.onerror = (event: any) => {
        if (resolved) return;
        if (event.error !== "no-speech" && event.error !== "aborted") {
          console.error("[OWW] Command capture error:", event.error);
        }
      };

      recognition.onend = () => {
        if (!resolved) {
          resolved = true;
          resumeOnnx();
          resolve("");
        }
      };

      try { recognition.start(); } catch {
        resolved = true;
        resumeOnnx();
        resolve("");
      }

      // Timeout safety
      setTimeout(() => {
        if (!resolved) {
          resolved = true;
          try { recognition.stop(); } catch { /* */ }
          resumeOnnx();
          resolve("");
        }
      }, 10000);
    });
  }, []);

  return { start, stop, listenOnce };
}
