export const READY = new Set(["DONE", "REUSED"]);

export const label = (value) => String(value || "").replaceAll("_", " ");

export const statusClass = (value) => {
  const status = String(value || "").toUpperCase();
  if (status === "DONE") return "done";
  if (status === "REUSED") return "reused";
  if (status === "RUNNING") return "running";
  if (status === "ACTION_REQUIRED") return "action-required";
  if (
    status === "FAILED" ||
    status === "MISSING" ||
    status === "STALE" ||
    status === "UNVERIFIED" ||
    status.startsWith("FAILED") ||
    status.startsWith("PAUSED")
  )
    return "failed";
  if (status.includes("WAITING") || status === "STOPPED" || status === "QUEUED")
    return "waiting";
  return "pending";
};

export const formatBytes = (bytes) =>
  bytes == null
    ? ""
    : bytes < 1024 * 1024
      ? `${Math.round(bytes / 1024)} KB`
      : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export const formatDate = (value) =>
  value
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "—";

export const artifactUrl = (base, path, version = "") => {
  const encoded = String(path)
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `${base}/${encoded}${version ? `?v=${version}` : ""}`;
};

export function previewFramesFromTimeline(timeline, base, count = 10) {
  const beats = Array.isArray(timeline?.beats)
    ? timeline.beats.filter((beat) => beat && (beat.image || beat.source))
    : [];
  const total = Math.max(1, Math.min(20, Math.round(Number(count) || 10)));
  if (!beats.length) return [];
  return Array.from({ length: total }, (_, sample) => {
    const index = Math.min(beats.length - 1, Math.floor(sample * beats.length / total));
    const beat = beats[index];
    const isVideo = String(beat.media_type || "image").toLowerCase() === "video";
    const duration = Math.max(0, Number(beat.duration) || ((Number(beat.end) || 0) - (Number(beat.start) || 0)));
    return {
      kind: isVideo ? "video" : "image",
      src: artifactUrl(base, beat.image || beat.source),
      mediaStart: isVideo ? duration / 2 : 0,
      label: `${isVideo ? "Video" : "Image"} beat ${String(beat.beat_id || index + 1).replace(/^video_/, "")}`,
    };
  });
}

export const SUBTITLE_PREVIEW_TEXT =
  "This a subtitle preview for test, thank you for your attention to this matter!";

// Bottom offsets mirroring build_timeline.SUBTITLE_POSITION_FRACTIONS (of frame height).
export const SUBTITLE_POSITION_OFFSETS = { low: 0.045, standard: 0.075, high: 0.13 };

// Pixel margin mirroring build_timeline.subtitle_margin_v (custom percent/px included).
export function subtitleMarginPx(position, offsetValue, offsetUnit, height = 1920) {
  if (position === "custom") {
    const raw = Number(offsetValue);
    const value = Number.isFinite(raw) ? raw : 10;
    if (offsetUnit === "px")
      return Math.max(0, Math.min(Math.round(value), Math.round(height * 0.5)));
    return Math.max(
      0,
      Math.min(Math.round((height * value) / 100), Math.round(height * 0.4)),
    );
  }
  return Math.round(
    (SUBTITLE_POSITION_OFFSETS[position] ?? SUBTITLE_POSITION_OFFSETS.standard) *
      height,
  );
}

export const SUBTITLE_FONT_SLUGS = {
  Roboto: "roboto",
  "Open Sans": "open-sans",
  Lato: "lato",
  Montserrat: "montserrat",
  Poppins: "poppins",
  "Noto Sans": "noto-sans",
  "Source Sans 3": "source-sans-3",
  Rubik: "rubik",
  "Atkinson Hyperlegible": "atkinson-hyperlegible",
  "Bebas Neue": "bebas-neue",
  Oswald: "oswald",
  "Zilla Slab": "zilla-slab",
  "Roboto Slab": "roboto-slab",
  Bitter: "bitter",
  "Titillium Web": "titillium-web",
  "Exo 2": "exo-2",
  "Encode Sans": "encode-sans",
  "DejaVu Sans": "dejavu-sans",
  "DejaVu Serif": "dejavu-serif",
  "Liberation Sans": "liberation-sans",
  "Liberation Serif": "liberation-serif",
  "Liberation Sans Narrow": "liberation-sans-narrow",
  "Nimbus Sans": "nimbus-sans",
  "Noto Sans Mono": "noto-sans-mono",
};

// Verified against the exact font files served by the panel.  A Latin-only face
// can still be selected for an English episode, but Persian/Arabic glyphs would
// silently fall back to another family without this warning.
export const SUBTITLE_FONT_SUPPORTS_PERSIAN = new Set([
  "DejaVu Sans",
  "Rubik",
]);

// First-caption word wrap mirroring build_timeline.wrap_caption: word-wrapped at
// maxChars, overflow folded into the last of maxLines lines (never dropped).
export function previewCaptionLines(text, maxWords, maxChars = 34, maxLines = 2) {
  const words = String(text || "")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, Math.max(1, Number(maxWords) || 6));
  const lines = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxChars && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines - 1);
    kept.push(lines.slice(maxLines - 1).join(" "));
    return kept;
  }
  return lines;
}

// Browser-side projection of build_timeline.build_cues_from_words.  The revision
// modal uses recorded word timings, so a Max words edit can be previewed before
// it rebuilds the timeline without pretending an old cue already has the new cuts.
export function previewCuesFromWords(words, maxWords, maxChars = 34, maxLines = 2) {
  const wordLimit = Math.max(1, Number(maxWords) || 6);
  const charLimit = Math.max(8, Number(maxChars) || 34) * Math.max(1, Number(maxLines) || 2);
  const cues = [];
  let chunk = [];
  const flush = () => {
    if (!chunk.length) return;
    const text = chunk.map((word) => word.text).join(" ").trim();
    if (text) {
      cues.push({
        start: chunk[0].start,
        end: chunk[chunk.length - 1].end,
        text,
        lines: previewCaptionLines(text, wordLimit, maxChars, maxLines),
      });
    }
    chunk = [];
  };
  for (const raw of words || []) {
    const text = String(raw?.text || "").trim();
    const start = Number(raw?.start);
    const end = Number(raw?.end);
    if (!text || !Number.isFinite(start) || !Number.isFinite(end)) continue;
    const candidate = [...chunk.map((word) => word.text), text].join(" ");
    if (chunk.length && (chunk.length >= wordLimit || candidate.length > charLimit)) flush();
    chunk.push({ text, start, end });
    if (/[.!?…]$/.test(text)) flush();
  }
  flush();
  return cues;
}

// Edges point from an input stage to the stage that consumes it.  Walk outward so a
// selection answers the useful operational question: "what will change if I change this?"
export function dependentNodeIds(edges, rootId) {
  if (!rootId) return new Set();
  const children = new Map();
  for (const { source, target } of edges || []) {
    if (!children.has(source)) children.set(source, []);
    children.get(source).push(target);
  }
  const result = new Set();
  const pending = [...(children.get(rootId) || [])];
  while (pending.length) {
    const id = pending.shift();
    if (id === rootId || result.has(id)) continue;
    result.add(id);
    pending.push(...(children.get(id) || []));
  }
  return result;
}

export function validateLaunchValues(values) {
  if (values.character_mode === "manual" && !values.character_id)
    throw new Error("Choose a manual character or switch Character to Auto.");
  if (Number(values.min_duration_seconds) > Number(values.max_duration_seconds))
    throw new Error(
      "Minimum duration cannot be greater than maximum duration.",
    );
  if (!values.telegram_low_size && !values.telegram_original)
    throw new Error("Choose at least one Telegram delivery output.");
  if (!Array.isArray(values.music_providers) || !values.music_providers.length)
    throw new Error("Choose at least one music provider.");
  const motionPrimitives = [
    "motion_allow_hold",
    "motion_allow_push",
    "motion_allow_pull",
    "motion_allow_directional_pans",
    "motion_allow_tilt",
    "motion_allow_pan_push",
    "motion_allow_pan_pull",
    "motion_allow_drift",
    "motion_allow_settle",
    "motion_allow_reveal_move",
  ];
  if (values.motion_enabled && !motionPrimitives.some((name) => values[name]))
    throw new Error("Enable at least one motion primitive.");
}
