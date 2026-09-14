export const READY = new Set(["DONE", "REUSED"]);

export const CONFIG_GROUP_CLIPBOARD_KIND =
  "yt-video-generation-pipeline/config-group";
export const CONFIG_GROUP_CLIPBOARD_VERSION = 1;

const editableGroupFields = (group) =>
  (Array.isArray(group?.fields) ? group.fields : []).filter(
    (field) => field?.name && field.type !== "readonly",
  );

function clipboardFieldValue(field, values) {
  if (Object.prototype.hasOwnProperty.call(values || {}, field.name))
    return values[field.name];
  if (Object.prototype.hasOwnProperty.call(field, "default")) return field.default;
  if (field.type === "toggle") return false;
  if (field.type === "priority") return [];
  return "";
}

// A deliberately readable, versioned envelope makes copied sections useful both
// to humans and to future clients while preventing an arbitrary JSON object from
// being mistaken for settings from this panel.
export function serializeConfigGroup(group, values, copiedAt = new Date().toISOString()) {
  if (!group?.id) throw new Error("This settings section has no stable identifier.");
  const fields = editableGroupFields(group);
  if (!fields.length) throw new Error("This section has no editable settings to copy.");
  const settings = Object.fromEntries(
    fields.map((field) => [field.name, clipboardFieldValue(field, values)]),
  );
  return JSON.stringify({
    kind: CONFIG_GROUP_CLIPBOARD_KIND,
    version: CONFIG_GROUP_CLIPBOARD_VERSION,
    group_id: group.id,
    group_title: group.title || group.id,
    copied_at: copiedAt,
    settings,
  }, null, 2);
}

function validateClipboardField(field, value) {
  const name = field.label || field.name;
  if (field.type === "toggle") {
    if (typeof value !== "boolean") throw new Error(`${name} must be true or false.`);
    return;
  }
  if (field.type === "priority") {
    if (!Array.isArray(value) || value.some((item) => typeof item !== "string"))
      throw new Error(`${name} must be a list of providers.`);
    if (!value.length) throw new Error(`${name} must contain at least one provider.`);
    if (new Set(value).size !== value.length)
      throw new Error(`${name} cannot contain duplicate providers.`);
    const allowed = new Set((field.options || []).map((option) => option.value));
    if (allowed.size && value.some((item) => !allowed.has(item)))
      throw new Error(`${name} contains an unavailable option.`);
    return;
  }
  if (field.type === "number") {
    if ((typeof value !== "number" && typeof value !== "string") || value === "")
      throw new Error(`${name} must be a number.`);
    const number = Number(value);
    if (!Number.isFinite(number)) throw new Error(`${name} must be a finite number.`);
    if (field.min != null && number < Number(field.min))
      throw new Error(`${name} cannot be less than ${field.min}.`);
    if (field.max != null && number > Number(field.max))
      throw new Error(`${name} cannot be greater than ${field.max}.`);
    return;
  }
  if (typeof value !== "string") throw new Error(`${name} must be text.`);
  if (field.required && !value.trim()) throw new Error(`${name} is required.`);
  if (field.maxLength != null && value.length > Number(field.maxLength))
    throw new Error(`${name} exceeds its ${field.maxLength}-character limit.`);
  if (field.type === "color" && !/^#[0-9a-fA-F]{6}$/.test(value))
    throw new Error(`${name} must be a six-digit hex colour.`);
  if (field.type === "select" && !field.searchable) {
    const allowed = new Set((field.options || []).map((option) => option.value));
    if (!allowed.has(value))
      throw new Error(`${name} contains an unavailable option.`);
  }
}

function validateClipboardRelationships(settings, currentValues = {}) {
  const merged = { ...currentValues, ...settings };
  if (
    "min_duration_seconds" in settings &&
    "max_duration_seconds" in settings &&
    Number(merged.min_duration_seconds) > Number(merged.max_duration_seconds)
  ) throw new Error("Minimum duration cannot be greater than maximum duration.");
  if (
    "aspect_ratio" in settings &&
    merged.content_project === "q_station" &&
    merged.aspect_ratio !== "9:16"
  ) throw new Error("Q Station requires the 9:16 frame format.");
  if (
    ("telegram_low_size" in settings || "telegram_original" in settings) &&
    !merged.telegram_low_size && !merged.telegram_original
  ) throw new Error("At least one Telegram delivery output must be enabled.");
  if (
    "show_watermark" in settings && merged.show_watermark &&
    !String(merged.watermark_text || "").trim()
  ) throw new Error("Watermark text is required when the watermark is enabled.");
  if (
    "character_mode" in settings && merged.character_mode === "manual" &&
    !merged.character_id
  ) throw new Error("A character must be selected in manual character mode.");
  const motionPrimitives = [
    "motion_allow_hold", "motion_allow_push", "motion_allow_pull",
    "motion_allow_directional_pans", "motion_allow_tilt", "motion_allow_pan_push",
    "motion_allow_pan_pull", "motion_allow_drift", "motion_allow_settle",
    "motion_allow_reveal_move",
  ];
  if (
    "motion_enabled" in settings && merged.motion_enabled &&
    !motionPrimitives.some((name) => merged[name])
  ) throw new Error("At least one Motion primitive must be enabled.");
}

export function parseConfigGroup(text, group, currentValues = {}) {
  if (typeof text !== "string" || !text.trim())
    throw new Error("The clipboard is empty.");
  if (text.length > 1_000_000)
    throw new Error("The clipboard content is too large to be a settings section.");
  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new Error("The clipboard does not contain valid JSON settings.");
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload))
    throw new Error("The clipboard does not contain a settings section.");
  if (payload.kind !== CONFIG_GROUP_CLIPBOARD_KIND)
    throw new Error("The clipboard was not copied from a panel settings section.");
  if (payload.version !== CONFIG_GROUP_CLIPBOARD_VERSION)
    throw new Error(`Clipboard format version ${String(payload.version)} is not supported.`);
  if (payload.group_id !== group?.id)
    throw new Error(`These settings belong to “${payload.group_title || payload.group_id || "another section"}”, not “${group?.title || group?.id}”.`);
  if (!payload.settings || typeof payload.settings !== "object" || Array.isArray(payload.settings))
    throw new Error("The copied section has no valid settings object.");

  const fields = editableGroupFields(group);
  const expected = new Set(fields.map((field) => field.name));
  const received = Object.keys(payload.settings);
  const unknown = received.filter((name) => !expected.has(name));
  const missing = fields.filter(
    (field) => !Object.prototype.hasOwnProperty.call(payload.settings, field.name),
  );
  if (unknown.length)
    throw new Error(`The copied section contains unknown setting “${unknown[0]}”.`);
  if (missing.length)
    throw new Error(`The copied section is missing “${missing[0].label || missing[0].name}”.`);

  const settings = {};
  for (const field of fields) {
    const value = payload.settings[field.name];
    validateClipboardField(field, value);
    settings[field.name] = value;
  }
  validateClipboardRelationships(settings, currentValues);
  return settings;
}

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
