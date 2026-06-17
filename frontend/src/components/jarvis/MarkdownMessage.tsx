import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function replaceExpressionsToEmojis(src: string): string {
  if (!src) return src;

  const emojiMap: Record<string, string> = {
    "slightly raised eyebrow": "🤨",
    "raised eyebrow": "🤨",
    "eyebrow": "🤨",
    "smiling": "😊",
    "smile": "😊",
    "grinning": "😀",
    "grin": "😀",
    "chuckles": "😆",
    "chuckle": "😆",
    "laughs": "😆",
    "laugh": "😆",
    "laughing": "😆",
    "sighs": "😔",
    "sigh": "😔",
    "winks": "😉",
    "wink": "😉",
    "nodding": "🙂",
    "nods": "🙂",
    "nod": "🙂",
    "thinking": "🤔",
    "think": "🤔",
    "thoughtful": "🤔",
    "concerned": "😟",
    "worried": "😟",
    "bows": "🙇‍♂️",
    "bow": "🙇‍♂️",
    "saluting": "🫡",
    "salute": "🫡",
    "smirks": "😏",
    "smirk": "😏",
    "surprised": "😮",
    "gasp": "😮",
    "shrugs": "🤷‍♂️",
    "shrug": "🤷‍♂️",
    "clears throat": "🗣️",
    "clear throat": "🗣️",
    "facepalm": "🤦‍♂️",
    "facepalms": "🤦‍♂️",
    "thumbs up": "👍",
    "frowns": "🙁",
    "frown": "🙁",
    "glares": "😠",
    "glare": "😠",
    "sighs deeply": "😔",
    "chuckles softly": "🤭",
    "smiles warmly": "😊",
    "grins widely": "😁"
  };

  const actionKeywords = [
    "sarcasm", "sarcastic", "pause", "dry", "whisper", "aside", 
    "laugh", "chuckle", "sigh", "throat", "cough", "smirk", 
    "wink", "nod", "shrug", "bow", "salute", "gasp", "frown", 
    "glare", "gesture", "dramatic", "ironic", "playful", "warmly",
    "mock", "hesitate", "silent", "quietly", "under breath", "giggle", "giggles"
  ];

  // Replace parenthesized expressions: (slightly raised eyebrow)
  let t = src.replace(/\(([^)]+)\)/g, (match, p1) => {
    const cleaned = p1.trim().toLowerCase();
    
    // Check if it's in the emoji map
    if (emojiMap[cleaned]) return emojiMap[cleaned];
    for (const [key, emoji] of Object.entries(emojiMap)) {
      if (cleaned.includes(key) || key.includes(cleaned)) {
        return emoji;
      }
    }
    
    // If it's a stage direction/action but doesn't have an emoji, strip it
    if (actionKeywords.some(kw => cleaned.includes(kw))) {
      return "";
    }
    
    return match;
  });

  // Replace asterisk actions: *slightly raised eyebrow* or *sighs*
  t = t.replace(/\*([^*]+)\*/g, (match, p1) => {
    const cleaned = p1.trim().toLowerCase();
    
    if (emojiMap[cleaned]) return emojiMap[cleaned];
    for (const [key, emoji] of Object.entries(emojiMap)) {
      if (cleaned === key || cleaned === key + "s" || cleaned === key + "ing") {
        return emoji;
      }
    }
    
    if (actionKeywords.some(kw => cleaned.includes(kw))) {
      return "";
    }
    
    return match;
  });

  // Clean up any extra/double spaces that might result from stripping brackets
  t = t.replace(/[ \t]{2,}/g, " ");
  t = t.replace(/ \n/g, "\n");
  t = t.replace(/\n /g, "\n");
  
  return t.trim();
}

/**
 * Safety-net normalizer (mirrors backend _fix_markdown). Ensures bullets/headers
 * render even if a reply slips through without proper blank lines. Idempotent;
 * leaves inline emphasis, prices, and math untouched.
 */
function normalizeMarkdown(src: string): string {
  if (!src) return src;
  
  // Convert parenthesized and asterisk action gestures into emojis
  let t = replaceExpressionsToEmojis(src);

  // Merge a lone bullet-marker line with the content on the next line.
  t = t.replace(/^([ \t]*)([*\-+])[ \t]*\n+[ \t]*(?=\S)/gm, "$1$2 ");
  t = t.replace(/^([ \t]*)[•▪◦·‣]\s+/gm, "$1- ");
  for (const g of ["•", "▪", "◦"]) {
    if (t.split(g).length - 1 >= 2) t = t.split(` ${g} `).join("\n- ");
  }
  const bullet = /^[ \t]*([*\-+]|\d+\.)\s+\S/;
  const out: string[] = [];
  for (const ln of t.split("\n")) {
    const curB = bullet.test(ln);
    if (out.length && out[out.length - 1].trim()) {
      const prevB = bullet.test(out[out.length - 1]);
      if ((curB && !prevB) || (prevB && !curB && ln.trim())) out.push("");
    }
    out.push(ln);
  }
  return out.join("\n");
}

/**
 * Renders assistant message text as styled markdown (bold, lists, links, code)
 * so the chat panel reads like Claude/ChatGPT instead of showing raw asterisks.
 * Styling uses Tailwind core utilities only (no typography plugin required).
 */
export default function MarkdownMessage({ text }: { text: string }) {
  return (
    <div className="leading-relaxed space-y-2 break-words">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className="leading-relaxed mb-2">{children}</p>,
          strong: ({ children }) => <strong className="font-extrabold text-[#00ffcc] tracking-wide">{children}</strong>,
          em: ({ children }) => <em className="italic text-yellow-300">{children}</em>,
          ul: ({ children }) => <ul className="list-disc pl-5 space-y-1">{children}</ul>,
          ol: ({ children }) => <ol className="list-decimal pl-5 space-y-1">{children}</ol>,
          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
          h1: ({ children }) => <h1 className="text-base font-semibold mt-1">{children}</h1>,
          h2: ({ children }) => <h2 className="text-sm font-semibold mt-1">{children}</h2>,
          h3: ({ children }) => <h3 className="text-sm font-semibold mt-1">{children}</h3>,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer" className="text-primary underline underline-offset-2">
              {children}
            </a>
          ),
          code: ({ children }) => (
            <code className="rounded bg-black/30 px-1 py-0.5 text-[0.85em] font-mono">{children}</code>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-jarvis-border/50 pl-3 italic opacity-90">{children}</blockquote>
          ),
        }}
      >
        {normalizeMarkdown(text)}
      </ReactMarkdown>
    </div>
  );
}
