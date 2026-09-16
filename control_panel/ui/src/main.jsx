import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import "./studio.css";
import {
  READY,
  artifactUrl,
  formatBytes,
  formatDate,
  label,
  dependentNodeIds,
  dbToLinearGain,
  parseConfigGroup,
  previewCaptionLines,
  previewCuesFromWords,
  previewFramesFromTimeline,
  serializeConfigGroup,
  statusClass,
  subtitleMarginPx,
  SUBTITLE_FONT_SLUGS,
  SUBTITLE_FONT_SUPPORTS_PERSIAN,
  SUBTITLE_PREVIEW_TEXT,
  validateLaunchValues,
  wrapTextByCharacterLimit,
} from "./studio-utils.js";

async function writeClipboardText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Permission and non-secure-context failures use the local fallback below.
    }
  }
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.readOnly = true;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand?.("copy");
  textarea.remove();
  if (!copied) throw new Error("Clipboard access was denied by the browser.");
}

async function readClipboardText() {
  if (navigator.clipboard?.readText) {
    try {
      return await navigator.clipboard.readText();
    } catch {
      // Manual paste still works when programmatic clipboard permission is denied.
    }
  }
  return window.prompt("Paste the copied settings JSON here:");
}

const PHASE_LABELS = {
  creative: "Creative",
  visual: "Visuals",
  opening: "Opening",
  audio: "Audio",
  edit: "Edit & motion",
  render: "Render & QC",
  publish: "Publishing",
};

const TRANSITION_OPTIONS = [
  ["fade", "Fade"], ["dissolve", "Dissolve"], ["fadeblack", "Fade to black"],
  ["fadewhite", "Fade to white"], ["smoothleft", "Smooth left"],
  ["smoothright", "Smooth right"], ["wipeleft", "Wipe left"],
  ["wiperight", "Wipe right"], ["slideleft", "Slide left"],
  ["slideright", "Slide right"], ["cut", "Cut"],
];
async function request(url, options) {
  const headers = new Headers(options?.headers || {});
  headers.set("Accept", "application/json");
  const response = await fetch(url, { ...options, headers });
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json")
    ? await response.json().catch(() => ({}))
    : await response.text();
  if (!response.ok) {
    let message = typeof body === "object" ? body.error : "";
    if (!message && typeof body === "string") {
      const doc = new DOMParser().parseFromString(body, "text/html");
      message =
        doc.querySelector(".notice")?.textContent ||
        doc.querySelector("main")?.textContent ||
        `Request failed (${response.status})`;
    }
    throw new Error(
      String(message || `Request failed (${response.status})`)
        .trim()
        .slice(0, 600),
    );
  }
  return body;
}

const AUTO_UPDATE_KEY = "studio.autoUpdate";
const STALE_SOCKET_MS = 35000;

// A Studio tab can briefly be running an older bundle while the server has
// just been deployed.  Treat the graph response as an external boundary: a
// missing/partial graph must result in an empty workspace, never a React
// render error that hides the entire run.
function normalizeGraph(graph) {
  const source = graph && typeof graph === "object" ? graph : {};
  const nodes = Array.isArray(source.nodes)
    ? source.nodes.filter((node) => node && typeof node === "object")
    : [];
  const nodeIds = new Set(nodes.map((node) => node.id).filter(Boolean));
  const edges = Array.isArray(source.edges)
    ? source.edges.filter(
      (edge) =>
        edge &&
        typeof edge === "object" &&
        nodeIds.has(edge.source) &&
        nodeIds.has(edge.target),
    )
    : [];
  const phases = Array.isArray(source.phases)
    ? source.phases.filter((phase) => typeof phase === "string")
    : [...new Set(nodes.map((node) => node.phase).filter(Boolean))];
  return { ...source, nodes, edges, phases };
}

function normalizeRunPayload(payload) {
  const source = payload && typeof payload === "object" ? payload : {};
  return {
    ...source,
    job: source.job && typeof source.job === "object" ? source.job : {},
    graph: normalizeGraph(source.graph),
    activity: Array.isArray(source.activity) ? source.activity : [],
  };
}

function readAutoUpdate() {
  try {
    const stored = localStorage.getItem(AUTO_UPDATE_KEY);
    return stored === null ? true : stored !== "0";
  } catch {
    return true;
  }
}

const THEME_KEY = "studio.theme";

function readTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {}
  try {
    if (matchMedia("(prefers-color-scheme: light)").matches) return "light";
  } catch {}
  return "dark";
}

// Apply the persisted theme before React's first paint. The previous inline
// bootstrap was blocked by the Studio CSP and could briefly render the wrong theme.
document.documentElement.dataset.theme = readTheme();

function useTheme() {
  const [theme, setTheme] = useState(readTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {}
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "light" ? "#edf1f7" : "#080c13";
  }, [theme]);
  return [theme, () => setTheme((current) => (current === "light" ? "dark" : "light"))];
}

function ThemeToggle({ theme, onToggle }) {
  const light = theme === "light";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      title={light ? "Switch to dark theme" : "Switch to light theme"}
      aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
      aria-pressed={light}
    >
      <span aria-hidden="true">{light ? "☾" : "☀"}</span>
      <span>{light ? "Dark" : "Light"}</span>
    </button>
  );
}

function useWebSocketUpdates({ jobId, onChange, notify, enabled = true, onStatus }) {
  const change = useRef(onChange);
  const announce = useRef(notify);
  const report = useRef(onStatus);
  useEffect(() => {
    change.current = onChange;
    announce.current = notify;
    report.current = onStatus;
  });
  useEffect(() => {
    if (!enabled) {
      try {
        report.current?.("off");
      } catch {}
      return;
    }
    let socket, retry, watchdog, closed = false, opened = false;
    let lastMessage = 0, connectingSince = 0;
    const setStatus = (value) => {
      try {
        report.current?.(value);
      } catch {}
    };
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const endpoint = `${protocol}//${location.host}/api/ws${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`;
    const connect = () => {
      if (closed) return;
      setStatus(opened ? "reconnecting" : "connecting");
      connectingSince = Date.now();
      socket = new WebSocket(endpoint);
      socket.onopen = () => {
        connectingSince = 0;
        lastMessage = Date.now();
        if (opened) announce.current("Live updates restored", "Updates are arriving without refresh.");
        opened = true;
        setStatus("live");
      };
      socket.onmessage = (event) => {
        lastMessage = Date.now();
        try {
          if (JSON.parse(event.data).type === "changed") change.current();
        } catch {
          // Ignore malformed notifications; the next valid server event will reconcile state.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        setStatus("reconnecting");
        announce.current("Live updates reconnecting", "The workspace will reconnect automatically.", "warn");
        retry = setTimeout(connect, 3000);
      };
      socket.onerror = () => socket.close();
    };
    connect();
    // A socket that stays silent past the server heartbeats is half-dead:
    // recycle it so updates resume without a manual refresh.
    watchdog = setInterval(() => {
      if (closed || !socket) return;
      if (socket.readyState === WebSocket.OPEN && Date.now() - lastMessage > STALE_SOCKET_MS) {
        try {
          socket.close();
        } catch {}
      } else if (socket.readyState === WebSocket.CONNECTING && connectingSince && Date.now() - connectingSince > 15000) {
        try {
          socket.close();
        } catch {}
      }
    }, 5000);
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(watchdog);
      try {
        socket?.close();
      } catch {}
    };
  }, [jobId, enabled]);
}

const injectedSubtitleFontSources = new Set();
function subtitleFontSource(font, fontSources = {}) {
  return fontSources[font] || (SUBTITLE_FONT_SLUGS[font] ? `/api/fonts/${SUBTITLE_FONT_SLUGS[font]}` : "");
}

function previewFontFamily(font, fontSources = {}) {
  return subtitleFontSource(font, fontSources) ? font : "DejaVu Sans";
}

function ensureSubtitleFonts(fontSources = {}) {
  const sources = Object.fromEntries(
    Object.entries(SUBTITLE_FONT_SLUGS).map(([family, slug]) => [family, `/api/fonts/${slug}`]),
  );
  Object.assign(sources, fontSources);
  const css = Object.entries(sources)
    .filter(([family, source]) => family && source && !injectedSubtitleFontSources.has(`${family}|${source}`))
    .map(([family, source]) => {
      injectedSubtitleFontSources.add(`${family}|${source}`);
      return `@font-face{font-family:"${family}";src:url("${source}");font-display:swap;}`;
    })
    .join("\n");
  if (!css) return;
  const el = document.createElement("style");
  el.textContent = css;
  document.head.appendChild(el);
}

function useSubtitleFont(font, fontSources = {}) {
  const [status, setStatus] = useState("loading");
  const source = subtitleFontSource(font, fontSources);
  useEffect(() => {
    const family = previewFontFamily(font, fontSources);
    let cancelled = false;
    try {
      ensureSubtitleFonts(fontSources);
      if (!source) {
        setStatus("fallback");
        return undefined;
      }
      if (!document.fonts) {
        setStatus("ready");
        return undefined;
      }
      setStatus("loading");
      document.fonts
        .load(`700 20px "${family}"`, SUBTITLE_PREVIEW_TEXT)
        .then((faces) => {
          if (!cancelled) setStatus(faces.length ? "ready" : "fallback");
        })
        .catch(() => !cancelled && setStatus("fallback"));
    } catch {
      setStatus("fallback");
    }
    return () => {
      cancelled = true;
    };
  }, [font, source]);
  return status;
}

function SubtitleFontSpecimen({ values, fontSources = {} }) {
  const font = previewFontFamily(values.subtitle_font, fontSources);
  return (
    <div
      className="subtitle-font-specimen"
      style={{
        fontFamily: `"${font}", sans-serif`,
        fontWeight: values.subtitle_bold === false ? 400 : 700,
        fontStyle: values.subtitle_italic ? "italic" : "normal",
      }}
    >
      <span>Ag</span>
      <small>{font}</small>
    </div>
  );
}

function BrandPreview({ values, fontSources = {}, frames = [], backdropLabel = "Preview backdrop", logoUrl = "" }) {
  useSubtitleFont(values.title_font, fontSources);
  useSubtitleFont(values.watermark_font, fontSources);
  const frameKey = frames.map((frame) => `${frame.kind}:${frame.src}:${frame.mediaStart || 0}`).join("|");
  const [frameIndex, setFrameIndex] = useState(0);
  const [mediaFailed, setMediaFailed] = useState(false);
  useEffect(() => { setFrameIndex(0); }, [frameKey]);
  const safeFrameIndex = frames.length ? Math.min(frameIndex, frames.length - 1) : 0;
  const backdrop = frames[safeFrameIndex] || null;
  useEffect(() => { setMediaFailed(false); }, [safeFrameIndex, frameKey]);
  const landscape = values.aspect_ratio === "16:9";
  const frameWidth = landscape ? 480 : 270, frameHeight = landscape ? 270 : 480;
  const logoWidth = frameWidth * Math.min(40, Math.max(4, Number(values.logo_width_percent) || 14)) / 100;
  const mx = frameWidth * (Number(values.logo_margin_x_percent) || 0) / 100;
  const my = frameHeight * (Number(values.logo_margin_y_percent) || 0) / 100;
  const presetBox = (position, boxWidth, boxHeight = boxWidth) => {
    if (position === "custom") return {
      left: frameWidth * (Number(values.logo_custom_x_percent) || 0) / 100 - boxWidth / 2,
      top: frameHeight * (Number(values.logo_custom_y_percent) || 0) / 100 - boxHeight / 2,
    };
    const normalized = position === "center" ? "middle_center" : position || "top_right";
    const [vertical, horizontal] = normalized.split("_");
    return {
      left: horizontal === "left" ? mx : horizontal === "center" ? (frameWidth - boxWidth) / 2 : frameWidth - boxWidth - mx,
      top: vertical === "top" ? my : vertical === "middle" ? (frameHeight - boxHeight) / 2 : frameHeight - boxHeight - my,
    };
  };
  const logo = presetBox(values.logo_position, logoWidth);
  const logoVisible = Boolean(values.show_logo && logoUrl);
  const titleWidth = frameWidth * Math.min(90, Math.max(12, Number(values.title_max_width_percent) || 34)) / 100;
  const tmx = frameWidth * (Number(values.title_margin_x_percent) || 0) / 100;
  const tmy = frameHeight * (Number(values.title_margin_y_percent) || 0) / 100;
  let titleLeft, titleTop, titleTransform = "";
  if (values.title_position === "below_logo" && logoVisible) {
    titleLeft = logo.left + logoWidth / 2 - titleWidth / 2;
    titleTop = logo.top + logoWidth + frameHeight * (Number(values.title_logo_gap_percent) || 0) / 100;
  } else if (values.title_position === "below_logo") {
    titleLeft = frameWidth - titleWidth - tmx;
    titleTop = tmy;
  } else if (values.title_position === "custom") {
    titleLeft = frameWidth * (Number(values.title_custom_x_percent) || 0) / 100 - titleWidth / 2;
    titleTop = frameHeight * (Number(values.title_custom_y_percent) || 0) / 100;
  } else {
    const normalized = values.title_position === "center" ? "middle_center" : values.title_position || "top_right";
    const [vertical, horizontal] = normalized.split("_");
    titleLeft = horizontal === "left" ? tmx : horizontal === "center" ? (frameWidth - titleWidth) / 2 : frameWidth - titleWidth - tmx;
    titleTop = vertical === "top" ? tmy : vertical === "middle" ? frameHeight / 2 : frameHeight - tmy;
    titleTransform = vertical === "middle" ? "translateY(-50%)" : vertical === "bottom" ? "translateY(-100%)" : "";
  }
  titleLeft = Math.max(0, Math.min(frameWidth - titleWidth, titleLeft));
  const titleColour = /^#[0-9a-fA-F]{6}$/.test(values.title_font_colour || "") ? values.title_font_colour : "#FFFFFF";
  const titleOutline = /^#[0-9a-fA-F]{6}$/.test(values.title_outline_colour || "") ? values.title_outline_colour : "#000000";
  const outline = Math.min(8, Math.max(0, Number(values.title_outline) || 0)) * .25;
  const titleFontSize = Math.max(16, Math.min(200, Number(values.title_font_size) || 38));
  const titleCharactersPerLine = Math.max(1, Math.min(220, Math.round(Number(values.title_max_characters_per_line) || 42)));
  const titleText = String(values.title_text || values.topic || "Your video question appears here").trim();
  const titleLines = wrapTextByCharacterLimit(titleText, titleCharactersPerLine);
  const lineSpacing = Math.max(-10, Math.min(100, Number(values.title_line_spacing) || 0));
  const watermarkText = String(values.watermark_text || "").trim();
  const watermarkWidth = frameWidth * Math.min(90, Math.max(12, Number(values.watermark_max_width_percent) || 34)) / 100;
  const wmx = frameWidth * (Number(values.watermark_margin_x_percent) || 0) / 100;
  const wmy = frameHeight * (Number(values.watermark_margin_y_percent) || 0) / 100;
  let watermarkLeft, watermarkTop, watermarkTransform = "";
  if (values.watermark_position === "below_logo" && logoVisible) {
    watermarkLeft = logo.left + logoWidth / 2 - watermarkWidth / 2;
    watermarkTop = logo.top + logoWidth + frameHeight * (Number(values.watermark_logo_gap_percent) || 0) / 100;
  } else if (values.watermark_position === "below_logo") {
    watermarkLeft = frameWidth - watermarkWidth - wmx;
    watermarkTop = wmy;
  } else if (values.watermark_position === "custom") {
    watermarkLeft = frameWidth * (Number(values.watermark_custom_x_percent) || 0) / 100 - watermarkWidth / 2;
    watermarkTop = frameHeight * (Number(values.watermark_custom_y_percent) || 0) / 100;
  } else {
    const normalized = values.watermark_position === "center" ? "middle_center" : values.watermark_position || "bottom_right";
    const [vertical, horizontal] = normalized.split("_");
    watermarkLeft = horizontal === "left" ? wmx : horizontal === "center" ? (frameWidth - watermarkWidth) / 2 : frameWidth - watermarkWidth - wmx;
    watermarkTop = vertical === "top" ? wmy : vertical === "middle" ? frameHeight / 2 : frameHeight - wmy;
    watermarkTransform = vertical === "middle" ? "translateY(-50%)" : vertical === "bottom" ? "translateY(-100%)" : "";
  }
  watermarkLeft = Math.max(0, Math.min(frameWidth - watermarkWidth, watermarkLeft));
  const watermarkColour = /^#[0-9a-fA-F]{6}$/.test(values.watermark_font_colour || "") ? values.watermark_font_colour : "#FFFFFF";
  const watermarkOutline = /^#[0-9a-fA-F]{6}$/.test(values.watermark_outline_colour || "") ? values.watermark_outline_colour : "#000000";
  const watermarkOutlineWidth = Math.min(8, Math.max(0, Number(values.watermark_outline) || 0)) * .25;
  const watermarkFontSize = Math.max(16, Math.min(200, Number(values.watermark_font_size) || 28));
  const watermarkWordsPerLine = Math.max(1, Math.min(100, Math.round(Number(values.watermark_max_words_per_line) || 7)));
  const watermarkWords = watermarkText.split(/\s+/).filter(Boolean);
  const watermarkLines = [];
  for (let index = 0; index < watermarkWords.length; index += watermarkWordsPerLine)
    watermarkLines.push(watermarkWords.slice(index, index + watermarkWordsPerLine).join(" "));
  const watermarkLineSpacing = Math.max(-10, Math.min(100, Number(values.watermark_line_spacing) || 0));
  return (
    <div className="brand-preview">
      <div className="subtitle-preview-frame brand-preview-frame" style={{ width: frameWidth, aspectRatio: landscape ? "16 / 9" : "9 / 16" }}>
        <div className="subtitle-preview-fallback" />
        {!mediaFailed && backdrop?.kind === "video" && <video
          key={`${safeFrameIndex}:${backdrop.src}`}
          src={`${backdrop.src}#t=${Math.max(0, Number(backdrop.mediaStart) || 0).toFixed(2)}`}
          muted playsInline preload="metadata"
          onLoadedMetadata={(event) => { event.currentTarget.currentTime = Math.max(0, Number(backdrop.mediaStart) || 0); }}
          onError={() => setMediaFailed(true)}
        />}
        {!mediaFailed && backdrop?.kind !== "video" && backdrop?.src && <img
          key={`${safeFrameIndex}:${backdrop.src}`}
          src={backdrop.src}
          alt={backdrop.label || backdropLabel}
          onError={() => setMediaFailed(true)}
        />}
        {logoVisible && <img className="brand-preview-logo" src={logoUrl} alt="Uploaded channel logo" style={{ left: logo.left, top: logo.top, width: logoWidth, opacity: Number(values.logo_opacity) || 1 }} />}
        {values.show_title && <div className="brand-preview-title" style={{
          left: titleLeft, top: Math.max(0, titleTop), width: titleWidth, transform: titleTransform,
          fontFamily: `"${previewFontFamily(values.title_font, fontSources)}", sans-serif`,
          fontSize: `${Math.max(4, titleFontSize * .25)}px`,
          lineHeight: `${Math.max(1, (titleFontSize + lineSpacing) * .25)}px`,
          fontWeight: values.title_bold === false ? 400 : 700, fontStyle: values.title_italic ? "italic" : "normal",
          textAlign: values.title_text_align || "right", color: titleColour,
          WebkitTextStroke: outline ? `${outline}px ${titleOutline}` : "0 transparent", paintOrder: "stroke fill",
        }}>{titleLines.map((line, index) => <span key={index}>{line}</span>)}</div>}
        {values.show_watermark && watermarkText && <div className="brand-preview-watermark" style={{
          left: watermarkLeft, top: Math.max(0, watermarkTop), width: watermarkWidth, transform: watermarkTransform,
          fontFamily: `"${previewFontFamily(values.watermark_font, fontSources)}", sans-serif`,
          fontSize: `${Math.max(4, watermarkFontSize * .25)}px`,
          lineHeight: `${Math.max(1, (watermarkFontSize + watermarkLineSpacing) * .25)}px`,
          fontWeight: values.watermark_bold === false ? 400 : 700, fontStyle: values.watermark_italic ? "italic" : "normal",
          textAlign: values.watermark_text_align || "right", color: watermarkColour,
          opacity: Math.max(.05, Math.min(1, Number(values.watermark_opacity) || .72)),
          WebkitTextStroke: watermarkOutlineWidth ? `${watermarkOutlineWidth}px ${watermarkOutline}` : "0 transparent", paintOrder: "stroke fill",
        }}>{watermarkLines.map((line, index) => <span key={index}>{line}</span>)}</div>}
      </div>
      {frames.length > 1 && <div className="brand-frame-nav">
        <button type="button" disabled={safeFrameIndex === 0} onClick={() => setFrameIndex((index) => Math.max(0, index - 1))} aria-label="Previous preview frame">←</button>
        <div><b>{safeFrameIndex + 1} / {frames.length}</b><small>{backdrop?.label || `Timeline frame ${safeFrameIndex + 1}`}</small></div>
        <button type="button" disabled={safeFrameIndex >= frames.length - 1} onClick={() => setFrameIndex((index) => Math.min(frames.length - 1, index + 1))} aria-label="Next preview frame">→</button>
      </div>}
      <small>Live {landscape ? "16:9" : "9:16"} composition preview · {backdrop?.label || backdropLabel} · {values.title_text?.trim() ? "custom title" : "episode question"}</small>
    </div>
  );
}

// Live caption preview on a fixed 270x480 frame (480/1920 of the ASS PlayRes
// height, so sizes and bottom offsets match the burn-in math). Backdrops are
// tried in order: the run's own keyframe, the selected style anchor, gradient.
function SubtitlePreview({ values, backdrops, backdropLabel, note = "", fontSources = {} }) {
  const fontStatus = useSubtitleFont(values.subtitle_font, fontSources);
  const keys = (backdrops || []).filter(Boolean).join("|");
  const [bgIndex, setBgIndex] = useState(0);
  useEffect(() => {
    setBgIndex(0);
  }, [keys]);
  const list = (backdrops || []).filter(Boolean);
  const src = bgIndex < list.length ? list[bgIndex] : null;
  const maxWords = Math.min(12, Math.max(1, Number(values.subtitle_max_words) || 6));
  const lines = previewCaptionLines(SUBTITLE_PREVIEW_TEXT, maxWords);
  return (
    <div className="subtitle-preview">
      <div className="subtitle-preview-frame">
        {src ? (
          <img
            src={src}
            alt={backdropLabel || "Subtitle preview backdrop"}
            onError={() => setBgIndex((index) => index + 1)}
          />
        ) : (
          <div className="subtitle-preview-fallback" />
        )}
        <CaptionOverlay
          values={values}
          lines={lines}
          highlightFirst={Boolean(values.word_highlight)}
          fontSources={fontSources}
        />
      </div>
      <SubtitleFontSpecimen values={values} fontSources={fontSources} />
      <small>
        {backdropLabel || "Sample backdrop"} · first {maxWords}-word caption ·{" "}
        {previewFontFamily(values.subtitle_font, fontSources)}{" "}
        {Math.min(300, Math.max(24, Number(values.subtitle_font_size) || 56))}px
        {values.subtitle_position ? ` · ${values.subtitle_position}` : ""}
        {fontStatus === "loading" ? " · loading font…" : ""}
        {fontStatus === "fallback" ? " · font unavailable; using fallback" : ""}
        {note ? ` · ${note}` : ""}
      </small>
    </div>
  );
}

// Cue-by-cue browser for revisions.  Each item is an actual timeline cue, on its
// owning media beat, rather than a narration excerpt rewrapped in the browser.
function SubtitleCuePreview({ values, cues, fontSources = {} }) {
  const [index, setIndex] = useState(0);
  const [mediaFailed, setMediaFailed] = useState(false);
  const fontStatus = useSubtitleFont(values.subtitle_font, fontSources);
  const safe = cues.length ? Math.min(index, cues.length - 1) : 0;
  const cue = cues.length ? cues[safe] : null;
  const mediaKey = cue ? `${cue.kind}:${cue.src}:${cue.start}` : "none";
  useEffect(() => {
    setIndex(0);
  }, [cues.length]);
  useEffect(() => {
    setMediaFailed(false);
  }, [mediaKey]);
  if (!cue) return null;
  const beatLabel = /^video_opening_(.+)$/.exec(String(cue.beat_id || ""))
    ? `Opening · ${RegExp.$1.toUpperCase()}`
    : `Beat ${cue.beat_id}`;
  return (
    <div className="subtitle-preview">
      <div className="subtitle-preview-frame">
        {!mediaFailed && cue.kind === "video" && (
          <video
            key={mediaKey}
            src={`${cue.src}#t=${Math.max(0, cue.mediaStart || 0).toFixed(2)}`}
            muted
            playsInline
            preload="metadata"
            onLoadedMetadata={(event) => {
              event.currentTarget.currentTime = Math.max(0, cue.mediaStart || 0);
            }}
            onError={() => setMediaFailed(true)}
          />
        )}
        {!mediaFailed && cue.kind !== "video" && (
          <img
            key={mediaKey}
            src={cue.src}
            alt={`${beatLabel} backdrop`}
            onError={() => setMediaFailed(true)}
          />
        )}
        {mediaFailed && <div className="subtitle-preview-fallback" />}
        <CaptionOverlay
          values={values}
          lines={cue.lines.length ? cue.lines : ["…"]}
          highlightFirst={Boolean(values.word_highlight)}
          fontSources={fontSources}
        />
      </div>
      <SubtitleFontSpecimen values={values} fontSources={fontSources} />
      <div className="beat-nav">
        <button
          type="button"
          disabled={safe <= 0}
          onClick={() => setIndex(safe - 1)}
          aria-label="Previous beat"
        >
          ←
        </button>
        <small>
          {beatLabel} · caption {safe + 1}/{cues.length}
        </small>
        <button
          type="button"
          disabled={safe >= cues.length - 1}
          onClick={() => setIndex(safe + 1)}
          aria-label="Next beat"
        >
          →
        </button>
      </div>
      <small>
        Caption projected from the recorded word timings in the current style —
        the first word represents the active karaoke word.
        {fontStatus === "loading" ? " Loading font…" : ""}
        {fontStatus === "fallback" ? " Font unavailable; using fallback." : ""}
      </small>
    </div>
  );
}

// Caption overlay shared by the static preview and the beat browser. Geometry
// mirrors build_timeline on a 270x480 frame (480/1920 of the ASS PlayRes).
function CaptionOverlay({ values, lines, highlightFirst = false, fontSources = {} }) {
  const font = previewFontFamily(values.subtitle_font, fontSources);
  const size = Math.min(300, Math.max(24, Number(values.subtitle_font_size) || 56));
  const margin = subtitleMarginPx(
    values.subtitle_position,
    values.subtitle_offset_value,
    values.subtitle_offset_unit,
  );
  const colour = /^#[0-9a-fA-F]{6}$/.test(values.subtitle_font_colour || "")
    ? values.subtitle_font_colour
    : "#FFFFFF";
  const outlineColour = /^#[0-9a-fA-F]{6}$/.test(values.subtitle_outline_colour || "")
    ? values.subtitle_outline_colour
    : "#000000";
  const outline = Math.min(8, Math.max(0, Number(values.subtitle_outline) ?? 3));
  const outlinePx = outline > 0 ? Math.max(0.25, outline * 0.25) : 0;
  return (
    <div
      className="subtitle-preview-caption"
      style={{
        bottom: `${Math.round(margin * 0.25)}px`,
        fontFamily: `"${font}", sans-serif`,
        fontSize: `${Math.round(size * 0.25)}px`,
        fontWeight: values.subtitle_bold === false ? 400 : 700,
        fontStyle: values.subtitle_italic ? "italic" : "normal",
        color: colour,
        WebkitTextStroke: outlinePx ? `${outlinePx}px ${outlineColour}` : "0 transparent",
        paintOrder: "stroke fill",
        textShadow: "none",
      }}
    >
      {lines.map((line, index) => (
        <span key={index}>
          {line.split(" ").map((word, wordIndex, words) => (
            <span
              key={wordIndex}
              className={
                highlightFirst && index === 0 && wordIndex === 0 ? "active-word" : ""
              }
              style={
                highlightFirst && index === 0 && wordIndex === 0
                  ? { color: "#FFD700" }
                  : undefined
              }
            >
              {word}
              {wordIndex < words.length - 1 ? " " : ""}
            </span>
          ))}
          {index < lines.length - 1 && <br />}
        </span>
      ))}
    </div>
  );
}

function ConnectionStatus({ status, autoUpdate, onToggle, onRefresh }) {  const text =
    !autoUpdate || status === "off"
      ? "Paused"
      : status === "live"
        ? "Live"
        : status === "connecting"
          ? "Connecting…"
          : "Reconnecting…";
  const tone =
    !autoUpdate || status === "off"
      ? ""
      : status === "live"
        ? "ready"
        : status === "connecting"
          ? "warn"
          : "bad";
  return (
    <span className="conn-status">
      <span
        className={`provider ${tone}`}
        title={
          autoUpdate
            ? "Auto-update is on: instant events plus a refresh every 3s"
            : "Auto-update is paused"
        }
      >
        <i />
        {text}
      </span>
      <button
        type="button"
        className="conn-toggle"
        onClick={onToggle}
        title={autoUpdate ? "Pause automatic updates" : "Resume automatic updates"}
      >
        {autoUpdate ? "Pause" : "Resume"}
      </button>
      <button
        type="button"
        className="conn-toggle"
        onClick={onRefresh}
        title="Refresh now"
        aria-label="Refresh now"
      >
        ⟳
      </button>
    </span>
  );
}

function Toasts({ items, dismiss }) {
  return (
    <div
      className="toasts"
      role="region"
      aria-label="Notifications"
      aria-live="polite"
    >
      {items.map((item) => (
        <div key={item.id} className={`toast ${item.kind || ""}`}>
          <span className="toast-icon">
            {item.kind === "bad" ? "!" : item.kind === "warn" ? "…" : "✓"}
          </span>
          <div>
            <b>{item.title}</b>
            <span>{item.body}</span>
          </div>
          <button
            onClick={() => dismiss(item.id)}
            aria-label="Dismiss notification"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}

function StatusPill({ status }) {
  return (
    <span className={`state ${statusClass(status)}`}>{label(status)}</span>
  );
}

function ProviderHealth({ health }) {
  if (!health)
    return (
      <div className="provider-strip">
        <span className="provider pending">Checking services…</span>
      </div>
    );
  const providers = Object.entries(health.providers || {});
  return (
    <div className="provider-strip">
      <span className={`provider ${health.reachable ? "ready" : "bad"}`}>
        <i />
        Ordak {health.reachable ? "online" : "offline"}
      </span>
      {providers.map(([name, item]) => {
        const good =
          item.state === "ready" &&
          (item.logged_in === true || item.tabs === 0);
        const text = item.logged_in
          ? "signed in"
          : item.state === "ready"
            ? "idle"
            : label(item.state);
        return (
          <span className={`provider ${good ? "ready" : "bad"}`} key={name}>
            <i />
            {name} · {text}
          </span>
        );
      })}
    </div>
  );
}

function SearchableSelect({ field, value, onChange, disabled = false }) {
  const id = `field-${field.name}`;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const options = field.options || [];
  const selected = options.find((option) => option.value === value);
  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? options.filter((option) =>
        `${option.label} ${option.value}`.toLowerCase().includes(needle),
      )
    : options;
  const pick = (option) => {
    if (!option) return;
    onChange(field.name, option.value);
    setQuery("");
    setOpen(false);
    setActive(0);
  };
  return (
    <label
      className={`field ${field.width === "half" ? "half" : ""} ${field.advanced ? "advanced-field" : ""} ${disabled ? "field-off" : ""}`}
      htmlFor={id}
    >
      <span>
        {field.label}
        {field.required && <i>required</i>}
      </span>
      <div className="search-select">
        <input
          id={id}
          value={open ? query : selected?.label || ""}
          placeholder="Type to search…"
          disabled={disabled}
          autoComplete="off"
          onFocus={() => {
            setQuery("");
            setActive(0);
            setOpen(true);
          }}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 200)}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              setOpen(true);
              setActive((index) => Math.min(index + 1, Math.max(0, filtered.length - 1)));
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              setActive((index) => Math.max(index - 1, 0));
            } else if (event.key === "Enter") {
              if (open && filtered.length) {
                event.preventDefault();
                pick(filtered[Math.min(active, filtered.length - 1)]);
              }
            } else if (event.key === "Escape") {
              setQuery("");
              setOpen(false);
            }
          }}
        />
        {open && (
          <div className="search-options" role="listbox">
            <span className="search-count">
              {filtered.length}/{options.length} shown — ↑↓ to move, Enter to pick
            </span>
            {filtered.map((option, index) => (
              <button
                type="button"
                key={option.value}
                className={`${option.value === value ? "selected" : ""} ${index === active ? "active" : ""} ${option.recommended ? "recommended" : ""}`}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActive(index)}
                onClick={() => pick(option)}
              >
                <i>{option.value === value ? "✓" : ""}</i>
                {option.label}
                {["subtitle_font", "title_font", "watermark_font"].includes(field.name) && SUBTITLE_FONT_SLUGS[option.value] != null && !SUBTITLE_FONT_SUPPORTS_PERSIAN.has(option.value)
                  ? " · Latin only"
                  : ""}
              </button>
            ))}
            {!filtered.length && (
              <span className="no-match">No matches — clear the search.</span>
            )}
          </div>
        )}
      </div>
      {field.help && <small>{field.help}</small>}
    </label>
  );
}

function ColourField({ field, value, onChange, gated = false }) {
  const id = `field-${field.name}`;
  const safe = /^#[0-9a-fA-F]{6}$/.test(value || "") ? value : "#FFFFFF";
  return (
    <label
      className={`field ${field.name === "title_text" ? "title-text-field" : ""} ${field.width === "half" ? "half" : ""} ${field.advanced ? "advanced-field" : ""} ${gated ? "field-off" : ""}`}
      htmlFor={id}
    >
      <span>
        {field.label}
        {field.required && <i>required</i>}
      </span>
      <div className="color-row">
        <input
          id={id}
          type="color"
          value={safe}
          disabled={gated || undefined}
          onChange={(event) => onChange(field.name, event.target.value.toUpperCase())}
        />
        <input
          type="text"
          value={value ?? ""}
          maxLength={7}
          spellCheck={false}
          disabled={gated || undefined}
          onChange={(event) => onChange(field.name, event.target.value)}
          aria-label={`${field.label} hex value`}
        />
      </div>
      {(field.presets || []).length > 0 && (
        <div className="color-swatches">
          {(field.presets || []).map(([hex, name]) => (
            <button
              type="button"
              key={hex}
              className="swatch"
              style={{ background: hex }}
              title={name || hex}
              aria-label={`Use ${name || hex}`}
              disabled={gated || undefined}
              onClick={() => onChange(field.name, String(hex).toUpperCase())}
            />
          ))}
        </div>
      )}
      {field.help && <small>{field.help}</small>}
    </label>
  );
}

function Field({ field, value, onChange, allValues = {} }) {
  const id = `field-${field.name}`;
  const requirements = Array.isArray(field.requires)
    ? field.requires
    : field.requires
      ? [field.requires]
      : [];
  const gated = requirements.some(
    (requirement) => allValues == null || allValues[requirement.field] !== requirement.value,
  );
  if (gated && field.hideWhenGated) return null;
  const common = {
    id,
    name: field.name,
    value: value ?? "",
    required: field.required,
    min: field.min ?? undefined,
    max: field.max ?? undefined,
    step: field.step ?? undefined,
    maxLength: field.maxLength,
    placeholder: field.placeholder,
    disabled: gated || undefined,
    onChange: (e) => onChange(field.name, e.target.value),
  };
  if (field.type === "toggle")
    return (
      <label
        className={`toggle-field ${field.advanced ? "advanced-field" : ""} ${gated ? "field-off" : ""}`}
        htmlFor={id}
      >
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          disabled={gated || undefined}
          onChange={(e) => onChange(field.name, e.target.checked)}
        />
        <span className="switch" />
        <span>
          <b>{field.label}</b>
          {field.help && <small>{field.help}</small>}
        </span>
      </label>
    );
  if (field.type === "readonly")
    return (
      <label className="field">
        <span>{field.label}</span>
        <input id={id} value={field.default || ""} disabled />
      </label>
    );
  if (field.type === "color")
    return <ColourField field={field} value={value} onChange={onChange} gated={gated} />;
  if (field.type === "select" && field.searchable)
    return (
      <>
        <SearchableSelect field={field} value={value} onChange={onChange} disabled={gated} />
        {["subtitle_font", "title_font", "watermark_font"].includes(field.name) && SUBTITLE_FONT_SLUGS[value] != null && !SUBTITLE_FONT_SUPPORTS_PERSIAN.has(value) && (
          <small className="font-language-warning">
            This face is Latin-only. Persian/Arabic captions will fall back to DejaVu Sans; use Rubik or DejaVu Sans for a deliberate Persian look.
          </small>
        )}
      </>
    );
  if (field.type === "priority") {
    const selected = Array.isArray(value) ? value : [];
    const options = new Map(
      (field.options || []).map((option) => [option.value, option]),
    );
    const move = (index, direction) => {
      const next = [...selected];
      const target = index + direction;
      if (target < 0 || target >= next.length) return;
      [next[index], next[target]] = [next[target], next[index]];
      onChange(field.name, next);
    };
    return (
      <fieldset className="priority field">
        <legend>{field.label}</legend>
        <small>{field.help}</small>
        <div className="priority-list">
          {selected.map((provider, index) => (
            <div className="priority-item" key={provider}>
              <em>{index + 1}</em>
              <b>{options.get(provider)?.label || provider}</b>
              <button
                type="button"
                disabled={index === 0}
                onClick={() => move(index, -1)}
                aria-label={`Move ${provider} earlier`}
              >
                ↑
              </button>
              <button
                type="button"
                disabled={index === selected.length - 1}
                onClick={() => move(index, 1)}
                aria-label={`Move ${provider} later`}
              >
                ↓
              </button>
              <button
                type="button"
                disabled={selected.length === 1}
                onClick={() =>
                  onChange(
                    field.name,
                    selected.filter((item) => item !== provider),
                  )
                }
                aria-label={`Remove ${provider}`}
              >
                ×
              </button>
            </div>
          ))}
          {(field.options || [])
            .filter((option) => !selected.includes(option.value))
            .map((option) => (
              <button
                type="button"
                className="priority-add"
                key={option.value}
                onClick={() =>
                  onChange(field.name, [...selected, option.value])
                }
              >
                + Add {option.label}
              </button>
            ))}
        </div>
      </fieldset>
    );
  }
  return (
    <label
      className={`field ${field.width === "half" ? "half" : ""} ${field.advanced ? "advanced-field" : ""} ${gated ? "field-off" : ""}`}
      htmlFor={id}
    >
      <span>
        {field.label}
        {field.required && <i>required</i>}
      </span>
      {field.type === "textarea" ? (
        <textarea {...common} />
      ) : field.type === "select" ? (
        <select {...common}>
          {(field.options || []).map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={(option.disabledProjects || []).includes(allValues.content_project)}
            >
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input {...common} type={field.type === "number" ? "number" : "text"} />
      )}
      {field.help && <small>{field.help}</small>}
    </label>
  );
}

function StyleLibrary({ styles, loading, values, change }) {
  const selectedId = values.world_style_id || "";
  const policy = values.world_style_policy || "auto";
  const [preview, setPreview] = useState(null);
  const [deleted, setDeleted] = useState(() => new Set());
  const [deleting, setDeleting] = useState("");
  const select = (styleId, nextPolicy) => {
    change("world_style_id", styleId);
    change("world_style_policy", nextPolicy);
    if (nextPolicy !== "new") change("world_style_reference_id", "");
  };
  const remove = async (style) => {
    if (!window.confirm(`Delete “${style.display_name}” permanently? Its catalog entry and style files will be removed from disk.`)) return;
    setDeleting(style.style_id);
    try {
      await request(`/api/styles/${encodeURIComponent(values.content_project)}/${encodeURIComponent(style.style_id)}`, { method: "DELETE" });
      setDeleted((current) => new Set([...current, style.style_id]));
      if (selectedId === style.style_id) select("", "auto");
    } catch (failure) {
      window.alert(`Style was not deleted: ${failure.message}`);
    } finally {
      setDeleting("");
    }
  };
  const visibleStyles = styles.filter((style) => !deleted.has(style.style_id));
  return (
    <section className="style-library" aria-label="World style library">
      <div className="style-library-head">
        <div>
          <span className="eyebrow">STYLE LIBRARY</span>
          <h3>Choose the visual world</h3>
          <p>Anchors show the look; the smaller image is a real generated beat when available.</p>
        </div>
        {loading && <small>Loading previews…</small>}
      </div>
      <div className="style-mode-grid">
        <button
          type="button"
          className={`style-mode ${!selectedId && policy === "auto" ? "selected" : ""}`}
          aria-pressed={!selectedId && policy === "auto"}
          onClick={() => select("", "auto")}
        >
          <b>✦ Auto direction</b><span>Let the director reuse or create the best match.</span>
        </button>
        <button
          type="button"
          className={`style-mode ${!selectedId && policy === "new" ? "selected" : ""}`}
          aria-pressed={!selectedId && policy === "new"}
          onClick={() => select("", "new")}
        >
          <b>＋ Create a new style</b><span>Describe the look or upload a visual reference below; a new reusable anchor is created.</span>
        </button>
      </div>
      <div className="style-card-grid" aria-live="polite">
        {visibleStyles.map((style) => {
          const active = selectedId === style.style_id && policy === "reuse";
          return (
            <article
              key={style.style_id}
              className={`style-card ${active ? "selected" : ""}`}
            >
              <button type="button" className="style-card-main" aria-pressed={active} onClick={() => select(style.style_id, "reuse")}>
                <div className="style-images">
                  {style.anchor_available ? <img loading="lazy" src={style.anchor_url} alt={`${style.display_name} style anchor`} /> : <span className="style-image-empty">Preview unavailable</span>}
                  {style.sample_available && <div className="style-sample"><img loading="lazy" src={style.sample_url} alt={`${style.display_name} generated beat`} /><span>Generated beat</span></div>}
                </div>
                <div className="style-card-copy">
                  <b>{style.display_name}</b>
                  <span>{style.medium_family || "Visual style"}{style.texture_family ? ` · ${style.texture_family}` : ""}</span>
                  {style.palette_summary && <small>{style.palette_summary}</small>}
                </div>
              </button>
              <div className="style-card-actions">
                <button type="button" title={`Preview ${style.display_name}`} aria-label={`Preview ${style.display_name}`} onClick={() => setPreview(style)}>◉</button>
                <button type="button" className="danger" title={`Delete ${style.display_name}`} aria-label={`Delete ${style.display_name}`} disabled={deleting === style.style_id} onClick={() => remove(style)}>{deleting === style.style_id ? "…" : "⌫"}</button>
              </div>
              {active && <i className="style-selected-mark">✓ Selected</i>}
            </article>
          );
        })}
      </div>
      {preview && <div className="modal-back style-preview-back" role="dialog" aria-modal="true" aria-label={`${preview.display_name} preview`} onMouseDown={(event) => event.target === event.currentTarget && setPreview(null)}>
        <section className="modal style-preview-modal">
          <button type="button" className="icon close" onClick={() => setPreview(null)} aria-label="Close style preview">×</button>
          <span className="eyebrow">STYLE PREVIEW</span><h2>{preview.display_name}</h2>
          <img src={preview.preview_url || preview.anchor_url} alt={`${preview.display_name} large preview`} />
          {preview.palette_summary && <p>{preview.palette_summary}</p>}
        </section>
      </div>}
    </section>
  );
}

function StyleReferenceUpload({ value, change, previewUrl = "" }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(previewUrl);
  useEffect(() => { if (previewUrl && !preview) setPreview(previewUrl); }, [previewUrl, preview]);
  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try {
      const body = new FormData(); body.append("image", file);
      const result = await request("/api/style-reference-uploads", { method: "POST", body });
      change("world_style_reference_id", result.id);
      setPreview(result.preview_url || "");
    } catch (failure) {
      setError(failure.message);
    } finally { setUploading(false); }
  }
  return (
    <section className="style-reference-upload">
      <div><b>Visual style reference <small>optional</small></b><p>Use only for texture, palette, line work and mood. It will not copy people, text, logos, or composition.</p></div>
      <div className="style-reference-actions">
        <label className="upload-button">{uploading ? "Uploading…" : "Upload PNG, JPEG or WebP"}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={upload} /></label>
        {value && <button type="button" onClick={() => { change("world_style_reference_id", ""); setPreview(""); }}>Remove reference</button>}
      </div>
      {preview && <img src={preview} alt="Selected visual style reference" />}
      {value && !preview && <small className="style-reference-saved">A hash-pinned reference is saved for this run.</small>}
      {error && <small className="style-reference-error" role="alert">{error}</small>}
    </section>
  );
}

function LogoUpload({ value, change, previewUrl = "", onPreviewChange }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try {
      const body = new FormData(); body.append("logo", file);
      const result = await request("/api/logo-uploads", { method: "POST", body });
      if (!result?.id || !result.preview_url) throw new Error("The uploaded logo response was incomplete.");
      change("logo_upload_id", result.id);
      change("show_logo", true);
      onPreviewChange(result.preview_url);
    } catch (failure) {
      setError(failure.message);
    } finally { setUploading(false); }
  }
  return <section className="logo-upload">
    <div><b>Channel logo</b><p>Upload PNG, JPEG, or WebP up to 12 MiB. Transparency is preserved and the file is frozen into each run.</p></div>
    <div className="style-reference-actions">
      <label className="upload-button">{uploading ? "Validating logo…" : value ? "Replace logo" : "Upload logo"}<input type="file" accept="image/png,image/jpeg,image/webp" disabled={uploading} onChange={upload} /></label>
      {value && <button type="button" onClick={() => { change("logo_upload_id", ""); change("show_logo", false); onPreviewChange(""); }}>Remove logo</button>}
    </div>
    {previewUrl && <img src={previewUrl} alt="Uploaded channel logo preview" />}
    {error && <small className="style-reference-error" role="alert">{error}</small>}
  </section>;
}

function MusicLibrary({ value, change, previewUrl = "" }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [tracks, setTracks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [reloadToken, setReloadToken] = useState(0);
  const selectedHash = /^(?:library|existing):([a-f0-9]{64})$/.exec(value || "")?.[1] || "";
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true); setError("");
      let failure = null;
      for (let attempt = 0; attempt < 3 && !cancelled; attempt += 1) {
        try {
          const result = await request("/api/music-library");
          if (!cancelled) setTracks(Array.isArray(result?.tracks) ? result.tracks : []);
          failure = null;
          break;
        } catch (caught) {
          failure = caught;
          if (attempt < 2) await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
        }
      }
      if (!cancelled && failure) {
        const detail = failure instanceof TypeError || /failed to fetch/i.test(String(failure?.message))
          ? "The music library is temporarily unreachable. It will not affect your saved music; please retry."
          : String(failure?.message || "Could not load the music library. Please retry.");
        setError(detail);
      }
      if (!cancelled) setLoading(false);
    };
    void load();
    return () => { cancelled = true; };
  }, [reloadToken]);
  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try {
      const body = new FormData(); body.append("music", file);
      const result = await request("/api/music-uploads", { method: "POST", body });
      if (!result?.sha256 || !result.preview_url) throw new Error("The uploaded music response was incomplete.");
      change("music_upload_id", `library:${result.sha256}`);
      setReloadToken((current) => current + 1);
    } catch (failure) {
      setError(failure.message);
    } finally { setUploading(false); }
  }
  const hasSelectedCard = selectedHash && tracks.some((track) => track.id === selectedHash);
  return <section className="music-library style-reference-upload">
    <div><b>Background music library <small>optional</small></b><p>Uploaded files and music saved from provider runs remain selectable. Selecting one bypasses provider search and freezes a hash-pinned copy into the run.</p></div>
    <div className="style-reference-actions">
      <label className="upload-button">{uploading ? "Validating audio…" : "Upload music"}<input type="file" accept="audio/mpeg,audio/wav,audio/mp4,audio/ogg,audio/flac,.mp3,.wav,.m4a,.ogg,.flac" disabled={uploading} onChange={upload} /></label>
      {value && <button type="button" onClick={() => change("music_upload_id", "")}>Use providers instead</button>}
    </div>
    {loading && <small className="style-reference-saved">Loading saved music…</small>}
    {!loading && !tracks.length && <small className="style-reference-saved">No saved music yet. Upload a track or complete a provider-backed run.</small>}
    {previewUrl && value && !hasSelectedCard && <article className="music-card selected"><div><b>Current run music</b><small>Frozen selection</small></div><audio controls preload="metadata" src={previewUrl} /></article>}
    <div className="music-card-grid">
      {tracks.map((track) => {
        const selected = track.id === selectedHash;
        const origin = track.origin === "upload" ? "Uploaded" : track.origin === "provider" ? `Downloaded · ${track.provider}` : `Saved run · ${track.provider}`;
        return <article className={`music-card ${selected ? "selected" : ""}`} key={track.id}>
          <div className="music-card-heading"><span><b title={track.name}>{track.name}</b><small>{origin}{track.source_video_id ? ` · ${track.source_video_id}` : ""}</small></span><button type="button" disabled={selected} onClick={() => change("music_upload_id", `library:${track.id}`)}>{selected ? "Selected ✓" : "Select"}</button></div>
          <audio controls preload="metadata" src={track.preview_url} />
          <div className="music-card-meta"><small>{formatBytes(Number(track.bytes) || 0)}{track.duration_seconds ? ` · ${Number(track.duration_seconds).toFixed(1)}s` : ""}</small>{track.license && <small title={track.license}>License: {track.license}</small>}</div>
        </article>;
      })}
    </div>
    {error && <div className="music-library-error" role="alert"><small className="style-reference-error">{error}</small><button type="button" onClick={() => setReloadToken((current) => current + 1)}>Retry library</button></div>}
  </section>;
}

function NarrationPreview({ url, gainDb = 0 }) {
  const audio = useRef(null);
  const context = useRef(null);
  const source = useRef(null);
  const gain = useRef(null);
  const [audioError, setAudioError] = useState("");
  const linearGain = dbToLinearGain(gainDb);
  useEffect(() => {
    if (gain.current && context.current) {
      gain.current.gain.setTargetAtTime(linearGain, context.current.currentTime, 0.015);
    } else if (audio.current) {
      // Safe fallback for browsers without Web Audio; positive gain needs the graph.
      audio.current.volume = Math.min(1, linearGain);
    }
  }, [linearGain]);
  useEffect(() => () => {
    try { source.current?.disconnect(); } catch {}
    try { gain.current?.disconnect(); } catch {}
    context.current?.close().catch(() => {});
  }, []);
  const enableGainPreview = async () => {
    try {
      if (!context.current) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;
        const nextContext = new AudioContext();
        const nextSource = nextContext.createMediaElementSource(audio.current);
        const nextGain = nextContext.createGain();
        audio.current.volume = 1;
        nextSource.connect(nextGain).connect(nextContext.destination);
        context.current = nextContext; source.current = nextSource; gain.current = nextGain;
      }
      gain.current.gain.setValueAtTime(dbToLinearGain(gainDb), context.current.currentTime);
      if (context.current.state === "suspended") await context.current.resume();
      setAudioError("");
    } catch {
      setAudioError("Live dB preview is unavailable in this browser; the saved final mix value is unaffected.");
    }
  };
  if (!url) return null;
  const signedDb = `${Number(gainDb) > 0 ? "+" : ""}${Number(gainDb) || 0} dB`;
  return <section className="narration-preview"><div><b>Generated narration <small>{signedDb} live preview</small></b><p>Changing Narration volume updates this player immediately and the same dB value is used by the final mix.</p></div><audio ref={audio} controls preload="metadata" src={url} onPlay={enableGainPreview} />{audioError && <small className="style-reference-error">{audioError}</small>}</section>;
}

function SubtitleFontUpload({ change, onUploaded, fieldName = "subtitle_font", label = "subtitle" }) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  async function upload(event) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setUploading(true); setError("");
    try {
      const body = new FormData(); body.append("font", file);
      const result = await request("/api/subtitle-fonts", { method: "POST", body });
      if (!result?.font?.family || !result.font.font_url) throw new Error("The uploaded font response was incomplete.");
      onUploaded(result.font);
      change(fieldName, result.font.family);
    } catch (failure) {
      setError(failure.message);
    } finally { setUploading(false); }
  }
  return (
    <section className="subtitle-font-upload">
      <div><b>Upload {label} font</b><p>Use a licensed <code>.ttf</code> or <code>.otf</code> file (up to 16 MiB). It is shared by title and subtitle renders.</p></div>
      <label className="upload-button">{uploading ? "Validating font…" : "Upload font"}<input type="file" accept="font/ttf,font/otf,.ttf,.otf" disabled={uploading} onChange={upload} /></label>
      {error && <small className="style-reference-error" role="alert">{error}</small>}
    </section>
  );
}

function SettingsGroup({ group, values, change, replaceGroup, open, toggle, styles, stylesLoading, characters = [], subtitleBackdrops = null, subtitleBackdropLabel = "", subtitleBeats = null, subtitleNote = "", timelineBeats = -1, styleReferencePreview = "", brandingFrames = [], brandingBackdropLabel = "Preview backdrop", logoPreviewUrl = "", musicPreviewUrl = "", narrationPreviewUrl = "", uploadedFonts: sharedFonts, onFontUploaded }) {
  const [advanced, setAdvanced] = useState(false);
  const [localFonts, setLocalFonts] = useState([]);
  const [clipboardState, setClipboardState] = useState(null);
  const clipboardTimer = useRef(null);
  useEffect(() => () => clearTimeout(clipboardTimer.current), []);
  const reportClipboard = (message, bad = false) => {
    clearTimeout(clipboardTimer.current);
    setClipboardState({ message, bad });
    clipboardTimer.current = setTimeout(() => setClipboardState(null), bad ? 7000 : 3500);
  };
  const copyGroup = async () => {
    try {
      await writeClipboardText(serializeConfigGroup(group, values));
      reportClipboard(`${group.title} copied.`);
    } catch (failure) {
      reportClipboard(failure.message || "Could not copy this section.", true);
    }
  };
  const pasteGroup = async () => {
    try {
      const text = await readClipboardText();
      if (text == null) return;
      const next = parseConfigGroup(text, group, values);
      if (replaceGroup) replaceGroup(next);
      else Object.entries(next).forEach(([name, value]) => change(name, value));
      reportClipboard(`${group.title} replaced from clipboard.`);
    } catch (failure) {
      reportClipboard(failure.message || "Could not paste this section.", true);
    }
  };
  // Fonts uploaded during this form session must be pickable in every font
  // picker (subtitles and branding share one library); callers share one list
  // so an upload in one section is selectable in the other without re-upload.
  const uploadedFonts = sharedFonts || localFonts;
  const addUploadedFont = onFontUploaded || ((font) => setLocalFonts((current) => current.some((item) => item.family === font.family) ? current : [...current, font]));
  const [logoPreview, setLogoPreview] = useState(logoPreviewUrl);
  useEffect(() => setLogoPreview(logoPreviewUrl), [logoPreviewUrl]);
  const subtitleField = group.fields.find((field) => ["subtitle_font", "title_font", "watermark_font"].includes(field.name));
  const subtitleOptions = [
    ...(subtitleField?.options || []),
    ...uploadedFonts.filter((font) => !(subtitleField?.options || []).some((option) => option.value === font.family)),
  ];
  const subtitleFontSources = Object.fromEntries(
    subtitleOptions.filter((option) => option.font_url).map((option) => [option.value, option.font_url]),
  );
  const advancedCount = group.fields.filter((field) => field.advanced).length;
  return (
    <section className={`settings-group ${open ? "open" : ""}`}>
      <div className="group-header-row">
        <button
          type="button"
          className="group-head"
          onClick={toggle}
          aria-expanded={open}
        >
          <span>
            <b>{group.title}</b>
            <small>{group.description}</small>
          </span>
          <span>{open ? "−" : "+"}</span>
        </button>
        <div className="group-clipboard-actions" aria-label={`${group.title} clipboard actions`}>
          <button type="button" onClick={copyGroup} title={`Copy all ${group.title} settings`} aria-label={`Copy ${group.title} settings`}>
            <span aria-hidden="true">⧉</span> Copy
          </button>
          <button type="button" onClick={pasteGroup} title={`Replace all ${group.title} settings from clipboard`} aria-label={`Paste ${group.title} settings from clipboard`}>
            <span aria-hidden="true">▣</span> Paste
          </button>
        </div>
      </div>
      {clipboardState && (
        <div className={`group-clipboard-status ${clipboardState.bad ? "bad" : ""}`} role={clipboardState.bad ? "alert" : "status"}>
          {clipboardState.bad ? "Could not paste/copy: " : "✓ "}{clipboardState.message}
        </div>
      )}
      {open && (
        <div className="field-grid">
          {group.id === "visual" && <StyleLibrary styles={styles} loading={stylesLoading} values={values} change={change} />}
          {group.id === "visual" && values.world_style_policy === "new" && !values.world_style_id && <StyleReferenceUpload value={values.world_style_reference_id} change={change} previewUrl={styleReferencePreview} />}
          {group.id === "music" && <MusicLibrary value={values.music_upload_id} change={change} previewUrl={musicPreviewUrl} />}
          {group.id === "voice" && <NarrationPreview url={narrationPreviewUrl} gainDb={values.narration_gain_db} />}
          {group.id === "subtitles" && <SubtitleFontUpload change={change} onUploaded={addUploadedFont} />}
          {group.id === "branding" && <div className="branding-editor">
            <div className="branding-controls">
              <LogoUpload value={values.logo_upload_id} change={change} previewUrl={logoPreview} onPreviewChange={setLogoPreview} />
              <SubtitleFontUpload fieldName="title_font" label="branding" change={change} onUploaded={addUploadedFont} />
              {group.fields.filter((field) => field.name !== "logo_upload_id").map((field) => {
                const displayField = ["subtitle_font", "title_font", "watermark_font"].includes(field.name) ? { ...field, options: subtitleOptions } : field;
                return <Field key={field.name} field={displayField} value={values[field.name]} onChange={change} allValues={values} />;
              })}
            </div>
            <aside className="branding-preview-rail">
              <BrandPreview values={values} fontSources={subtitleFontSources} frames={brandingFrames} backdropLabel={brandingBackdropLabel} logoUrl={logoPreview} />
            </aside>
          </div>}
          {group.id === "subtitles" && subtitleBeats?.length > 0 && (
            <SubtitleCuePreview values={values} cues={subtitleBeats} fontSources={subtitleFontSources} />
          )}
          {group.id === "subtitles" && (
            <small className="timeline-info">
              {timelineBeats < 0
                ? "timeline: loading…"
                : timelineBeats === 0
                  ? "timeline: not built yet for this run"
                  : `timeline: ${timelineBeats} beats · ${subtitleBeats?.length || 0} previewable`}
            </small>
          )}
          {group.id === "subtitles" && !(subtitleBeats?.length > 0) && (
            <SubtitlePreview
              values={values}
              backdrops={subtitleBackdrops}
              backdropLabel={subtitleBackdropLabel}
              note={subtitleNote}
              fontSources={subtitleFontSources}
            />
          )}
          {group.fields
            .filter(() => group.id !== "branding")
            .filter((field) => group.id !== "visual" || !["world_style_id", "world_style_policy", "world_style_reference_id"].includes(field.name))
            .filter((field) => field.name !== "music_upload_id")
            .filter((field) => advanced || !field.advanced)
            .filter((field) => field.name !== "character_id" || values.character_mode === "manual")
            .map((field) => {
              let displayField = field.name === "character_id" ? {
                  ...field,
                  options: characters.length
                    ? [{ value: "", label: "Choose a character" }, ...characters.map((item) => ({
                        value: item.id,
                        label: item.presentation_name ? `${item.display_name} — ${item.presentation_name}` : item.display_name,
                      }))]
                    : field.options,
                } : field;
              if (["subtitle_font", "title_font", "watermark_font"].includes(field.name)) {
                displayField = { ...displayField, options: subtitleOptions };
              }
              if (group.id === "sfx" && field.name !== "sfx_enabled") {
                displayField = { ...displayField, requires: { field: "sfx_enabled", value: true } };
              }
              if (group.id === "motion" && !["motion_enabled", "motion_image_zoom_strength"].includes(field.name)) {
                displayField = { ...displayField, requires: { field: "motion_enabled", value: true } };
              }
              return <Field
                key={field.name}
                field={displayField}
                value={values[field.name]}
                onChange={change}
                allValues={values}
              />;
            })}
          {advancedCount > 0 && (
            <button
              type="button"
              className="advanced-toggle"
              onClick={() => setAdvanced((value) => !value)}
            >
              {advanced
                ? "Hide advanced settings"
                : `Show ${advancedCount} advanced settings`}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function NewRunForm({ schema, initial, onLaunched, notify }) {
  const [values, setValues] = useState(initial || {});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [styles, setStyles] = useState([]);
  const [stylesLoading, setStylesLoading] = useState(false);
  const [characters, setCharacters] = useState([]);
  const [openGroups, setOpenGroups] = useState(
    () => new Set(schema.groups.filter((group) => !group.collapsed).map((group) => group.id)),
  );
  const [uploadedFonts, setUploadedFonts] = useState([]);
  const addUploadedFont = (font) => setUploadedFonts((current) => current.some((item) => item.family === font.family) ? current : [...current, font]);
  useEffect(() => setValues(initial || {}), [initial]);
  useEffect(() => {
    const project = values.content_project;
    let cancelled = false;
    setStylesLoading(true);
    Promise.all([
      request(`/api/style-catalog?content_project=${encodeURIComponent(project)}`),
      request(`/api/character-catalog?content_project=${encodeURIComponent(project)}`),
    ])
      .then(([styleData, characterData]) => {
        if (cancelled) return;
        setStyles(styleData.styles || []);
        setCharacters(characterData.characters || []);
        setValues((current) => ({ ...current, character_mode: "auto", character_id: "" }));
      })
      .catch((failure) => !cancelled && notify("Project catalogs unavailable", failure.message, "warn"))
      .finally(() => !cancelled && setStylesLoading(false));
    return () => { cancelled = true; };
  }, [values.content_project]);
  useEffect(() => {
    if (values.content_project === "q_station" && values.aspect_ratio !== "9:16") {
      setValues((current) => ({ ...current, aspect_ratio: "9:16" }));
    }
  }, [values.content_project, values.aspect_ratio]);
  const change = (name, value) =>
    setValues((current) => ({ ...current, [name]: value }));
  const applicableGroups = schema.groups.filter(
    (group) =>
      !group.projects || group.projects.includes(values.content_project),
  );
  const styleAnchorFor = (styleId) =>
    styles.find((item) => item.style_id === styleId)?.anchor_url || "";
  const subtitleBackdrops = [
    styleAnchorFor(values.world_style_id),
    ...styles.map((item) => item.anchor_url),
  ].filter((url, index, all) => url && all.indexOf(url) === index);
  const selectedStyleAnchor = styleAnchorFor(values.world_style_id);
  const uploadedStylePreview = /^[a-f0-9]{32}$/.test(values.world_style_reference_id || "")
    ? `/api/style-reference-uploads/${values.world_style_reference_id}/preview`
    : "";
  const brandingFrames = selectedStyleAnchor || uploadedStylePreview ? [{
    kind: "image", src: selectedStyleAnchor || uploadedStylePreview,
    label: selectedStyleAnchor ? `${values.world_style_id} style anchor` : "Uploaded style reference",
  }] : [];
  const enabled = applicableGroups
    .flatMap((group) => group.fields)
    .filter((field) => field.type !== "readonly").length;
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      validateLaunchValues(values);
      const body = new URLSearchParams();
      Object.entries(values).forEach(([key, value]) => {
        if (typeof value === "boolean") {
          if (value) body.append(key, "on");
        } else if (Array.isArray(value)) body.append(key, value.join(","));
        else body.append(key, String(value ?? ""));
      });
      const response = await request("/launch", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      notify(
        "Pipeline launched",
        "The run is initialized and will appear in the dashboard.",
        "",
      );
      onLaunched(response?.job_id);
    } catch (failure) {
      setError(failure.message);
      notify("Launch failed", failure.message, "bad");
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="new-run-form" onSubmit={submit}>
      <div className="form-intro">
        <div>
          <span className="eyebrow">NEW PIPELINE RUN</span>
          <h2>Build the exact run you want</h2>
          <p>
            Essentials are open. Specialist controls stay close without getting
            in the way.
          </p>
          <div className="form-view-actions">
            <button
              type="button"
              onClick={() =>
                setOpenGroups(new Set(applicableGroups.map((group) => group.id)))
              }
            >
              Expand sections
            </button>
            <button type="button" onClick={() => setOpenGroups(new Set())}>
              Collapse sections
            </button>
          </div>
        </div>
        <div className="form-stat">
          <b>{enabled}</b>
          <span>available controls</span>
        </div>
      </div>
      {applicableGroups.map((group) => (
          <SettingsGroup
            key={group.id}
            group={group}
            values={values}
            change={change}
            replaceGroup={(settings) => setValues((current) => ({ ...current, ...settings }))}
            styles={styles}
            stylesLoading={stylesLoading}
            characters={characters}
            open={openGroups.has(group.id)}
            toggle={() =>
              setOpenGroups((current) => {
                const next = new Set(current);
                if (next.has(group.id)) next.delete(group.id);
                else next.add(group.id);
                return next;
              })
            }
            subtitleBackdrops={subtitleBackdrops}
            subtitleBackdropLabel={
              values.world_style_id
                ? "Style anchor backdrop"
                : "Sample style backdrop"
            }
            brandingFrames={brandingFrames}
            brandingBackdropLabel={values.world_style_id || uploadedStylePreview ? "Selected style reference" : "Select a style to preview its anchor"}
            uploadedFonts={uploadedFonts}
            onFontUploaded={addUploadedFont}
          />
      ))}
      {error && (
        <div className="inline-error" role="alert">
          <b>Could not launch</b>
          <span>{error}</span>
        </div>
      )}
      <div className="launch-bar">
        <div>
          <b>{values.topic || "Untitled episode"}</b>
          <span>
            {values.min_duration_seconds}–{values.max_duration_seconds}s ·{" "}
            {values.aspect_ratio} · {(values.music_providers || []).join(" → ")}
          </span>
        </div>
        <button
          className="primary compact"
          disabled={busy || !String(values.topic || "").trim()}
        >
          {busy ? "Starting pipeline…" : "Launch pipeline →"}
        </button>
      </div>
    </form>
  );
}

function RunRow({ job, open }) {
  const total = job.pipeline?.stage_count || 0,
    done = job.pipeline?.done || 0;
  const percent = total ? Math.min(100, Math.round((done / total) * 100)) : 0;
  return (
    <button className="run-row" onClick={() => open(job.job_id)}>
      <div className="run-id">
        <span>{job.video_id || "—"}</span>
        <i className={statusClass(job.status)} />
      </div>
      <div className="run-copy">
        <strong>{job.topic || "Untitled run"}</strong>
        <small>
          {formatDate(job.created_at)}
          {job.pipeline?.running ? ` · ${label(job.pipeline.running)}` : ""}
        </small>
        <div className="progress">
          <i style={{ width: `${percent}%` }} />
        </div>
      </div>
      <div className="run-progress">
        <b>
          {done}/{total || "—"}
        </b>
        <small>stages</small>
      </div>
      <StatusPill status={job.status} />
      <span className="arrow">→</span>
    </button>
  );
}

function creditValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  return new Intl.NumberFormat().format(value);
}

function CreditServiceCard({ service }) {
  const credits = service.credits;
  const state = service.status || "queued";
  const identity = service.email || service.plan || "Account details are loading…";
  const creditLine = credits
    ? credits.total != null
      ? `${creditValue(credits.remaining)} remaining of ${creditValue(credits.total)} ${credits.unit || "credits"}`
      : `${creditValue(credits.remaining)} ${credits.unit || "credits"} remaining`
    : state === "checking" || state === "queued"
      ? "Reading the visible account balance…"
      : "No readable balance was shown by the provider.";
  return (
    <article className={`credit-service ${state}`}>
      <div className="credit-service-top">
        <div>
          <span className="eyebrow">{service.label}</span>
          <strong>{identity}</strong>
        </div>
        <span className={`credit-state ${state}`}>{state === "checking" ? "Checking" : state.replaceAll("_", " ")}</span>
      </div>
      <b className="credit-balance">{creditLine}</b>
      {credits?.used != null && <small>Used: {creditValue(credits.used)} {credits.unit || "credits"}</small>}
      {service.message && <p>{service.message}</p>}
    </article>
  );
}

function CreditCheckModal({ value, close, retry }) {
  const running = value?.status === "running" || value?.status === "starting";
  const profiles = value?.profiles || [];
  const completedAt = value?.completed_at || value?.updated_at;
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="credit-check-title" onMouseDown={(event) => event.target === event.currentTarget && close()}>
      <section className="modal credit-modal">
        <button className="icon close" onClick={close} aria-label="Close credit check">×</button>
        <span className="eyebrow">BROWSER ACCOUNT CHECK</span>
        <h2 id="credit-check-title">Credits</h2>
        <p>
          {running
            ? "Opening the signed-in Chrome profile and checking each provider. Results appear as soon as they are ready."
            : value?.status === "failed"
              ? value.error || "The credit check could not start."
              : "All configured providers have finished checking."}
        </p>
        {profiles.length ? profiles.map((profile) => (
          <section className="credit-profile" key={profile.id}>
            <header>
              <div>
                <h3>{profile.label}</h3>
                <small>Chrome profile: {profile.id}{profile.vnc_port ? ` · VNC ${profile.vnc_port}` : ""}</small>
              </div>
              <span className={`credit-state ${profile.status || "queued"}`}>{profile.status || "queued"}</span>
            </header>
            <div className="credit-services">
              {(profile.services || []).map((service) => <CreditServiceCard key={service.key} service={service} />)}
            </div>
          </section>
        )) : (
          <div className="loading-line">{running ? "Preparing Chrome profile…" : "No configured profiles returned a result."}</div>
        )}
        <footer className="credit-modal-footer">
          <small>{completedAt ? `Last updated: ${formatDate(completedAt)}` : "Last updated: just now"}</small>
          {!running && <button className="secondary" onClick={retry}>Check again</button>}
        </footer>
      </section>
    </div>
  );
}

function Home({ open, go, page = "home", notify, theme, onToggleTheme }) {
  const [jobs, setJobs] = useState([]),
    [health, setHealth] = useState(null),
    [contract, setContract] = useState(null),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState("all"),
    [autoUpdate, setAutoUpdate] = useState(readAutoUpdate),
    [connStatus, setConnStatus] = useState("connecting"),
    [creditCheck, setCreditCheck] = useState(null),
    [creditModalOpen, setCreditModalOpen] = useState(false),
    dashboardDisconnected = useRef(false),
    contractReady = useRef(false),
    contractFailed = useRef(false),
    statusLoading = useRef(false);
  const load = () => {
    if (statusLoading.current) return Promise.resolve();
    statusLoading.current = true;
    return request("/api/status")
      .then((data) => {
        setJobs(data.jobs || []);
        setHealth(data.ordak);
        if (dashboardDisconnected.current)
          notify("Dashboard reconnected", "Live status is available again.");
        dashboardDisconnected.current = false;
      })
      .catch((error) => {
        if (!dashboardDisconnected.current)
          notify("Dashboard disconnected", error.message, "bad");
        dashboardDisconnected.current = true;
      })
      .finally(() => {
        statusLoading.current = false;
      });
  };
  const loadContract = () => {
    if (contractReady.current) return;
    request("/api/launch-schema")
      .then((value) => {
        setContract(value);
        contractReady.current = true;
        if (contractFailed.current)
          notify("Settings restored", "The launch form is ready again.");
        contractFailed.current = false;
      })
      .catch((error) => {
        if (!contractFailed.current)
          notify("Settings unavailable", error.message, "bad");
        contractFailed.current = true;
      });
  };
  useWebSocketUpdates({ onChange: load, notify, enabled: autoUpdate, onStatus: setConnStatus });
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    load();
    loadContract();
  }, []);
  useEffect(() => {
    if (!autoUpdate) return;
    const timer = setInterval(() => loadRef.current(), 3000);
    return () => clearInterval(timer);
  }, [autoUpdate]);
  const toggleAutoUpdate = () => {
    setAutoUpdate((current) => {
      const next = !current;
      try {
        localStorage.setItem(AUTO_UPDATE_KEY, next ? "1" : "0");
      } catch {}
      if (next) setTimeout(() => loadRef.current(), 50);
      return next;
    });
  };
  const startCreditCheck = () => {
    setCreditModalOpen(true);
    setCreditCheck({ status: "starting", profiles: [] });
    request("/api/credits/check", { method: "POST" })
      .then((result) => setCreditCheck(result))
      .catch((error) => {
        setCreditCheck({ status: "failed", error: error.message, profiles: [] });
        notify("Credit check unavailable", error.message, "bad");
      });
  };
  useEffect(() => {
    const checkId = creditCheck?.check_id;
    if (!creditModalOpen || !checkId || creditCheck?.status !== "running") return undefined;
    let cancelled = false;
    const refresh = () => request(`/api/credits/check/${encodeURIComponent(checkId)}`)
      .then((result) => !cancelled && setCreditCheck(result))
      .catch((error) => {
        if (!cancelled) setCreditCheck((current) => ({ ...current, status: "failed", error: error.message }));
      });
    const timer = setInterval(refresh, 900);
    refresh();
    return () => { cancelled = true; clearInterval(timer); };
  }, [creditModalOpen, creditCheck?.check_id, creditCheck?.status]);
  const shown = jobs.filter(
    (job) =>
      (status === "all" || statusClass(job.status) === status) &&
      `${job.video_id} ${job.topic}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const active = jobs.find((job) => job.live);
  if (page === "home") {
    return (
      <main className="home landing">
        <div className="landing-brand">
          <div>
            <span className="eyebrow">VIDEO GENERATION PIPELINE</span>
            <h1>Studio</h1>
          </div>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
        <section className="landing-actions" aria-label="Choose a Studio action">
          <button className="landing-card" onClick={() => go("/runs")}>
            <span className="landing-icon" aria-hidden="true">◫</span>
            <b>Previous runs</b>
            <small>Browse the status, progress, and output of earlier video runs.</small>
            <i aria-hidden="true">→</i>
          </button>
          <button className="landing-card primary-card" onClick={() => go("/new")}>
            <span className="landing-icon" aria-hidden="true">＋</span>
            <b>Create new video</b>
            <small>Set up a new video and start its generation pipeline.</small>
            <i aria-hidden="true">→</i>
          </button>
        </section>
      </main>
    );
  }
  return (
    <main className="home">
      <header className="brand">
        <div>
          <span className="eyebrow">VIDEO GENERATION PIPELINE</span>
          <button className="back page-back" onClick={() => go("/")}>← Studio</button>
        </div>
        <div className="brand-side">
          <button className="credit-check-button" onClick={startCreditCheck}>Check credits</button>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <ConnectionStatus
            status={connStatus}
            autoUpdate={autoUpdate}
            onToggle={toggleAutoUpdate}
            onRefresh={load}
          />
          <ProviderHealth health={health} />
        </div>
      </header>
      {page === "new" && (contract ? (
        <NewRunForm
          schema={contract.schema}
          initial={contract.defaults}
          notify={notify}
          onLaunched={(jobId) => {
            setTimeout(load, 700);
            if (jobId) open(jobId);
          }}
        />
      ) : (
        <div className="loading-card">Loading launch settings…</div>
      ))}
      {page === "runs" && <section className="runs">
        <div className="section-head">
          <div>
            <span className="eyebrow">HISTORY</span>
            <h2>Runs</h2>
          </div>
          <div className="run-tools">
            <input
              aria-label="Search runs"
              placeholder="Search topic or ID…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <select
              aria-label="Filter status"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              <option value="all">All statuses</option>
              <option value="running">Running</option>
              <option value="done">Done</option>
              <option value="failed">Needs attention</option>
              <option value="waiting">Waiting</option>
            </select>
          </div>
        </div>
        {shown.length ? (
          shown.map((job) => <RunRow key={job.job_id} job={job} open={open} />)
        ) : (
          <div className="no-runs">No runs match this view.</div>
        )}
      </section>}
      {creditModalOpen && (
        <CreditCheckModal
          value={creditCheck}
          close={() => setCreditModalOpen(false)}
          retry={startCreditCheck}
        />
      )}
    </main>
  );
}

function ArtifactNode({ data }) {
  const media = data.artifacts?.find(
    (item) =>
      item.exists && item.media && /\.(png|jpe?g|webp)$/i.test(item.path),
  );
  return (
    <div
      className={`node ${statusClass(data.status)} ${data.selected ? "selected" : ""} ${data.dependent ? "dependent" : ""}`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="node-top">
        <span>{PHASE_LABELS[data.phase] || data.kind}</span>
        <i />
      </div>
      {media && (
        <img
          className="node-image"
          src={artifactUrl(data.previewBase, media.path, media.updated_at)}
          alt=""
        />
      )}
      <strong>{data.title}</strong>
      <small>{label(data.status)}</small>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { artifact: ArtifactNode };

function PipelineBoard({ graph, selected, dependents, choose }) {
  return (
    <div className="pipeline-board">
      {graph.phases.map((phase) => {
        const nodes = graph.nodes.filter((node) => node.phase === phase);
        const beatNodes = nodes.filter((node) => node.id.startsWith("beat_image_"));
        const visibleNodes = nodes.filter((node) => !node.id.startsWith("beat_image_"));
        return (
          <section key={phase} className="phase-column">
            <header>
              <span>{PHASE_LABELS[phase]}</span>
              <b>
                {nodes.filter((node) => READY.has(node.status)).length}/
                {nodes.length}
              </b>
            </header>
            {visibleNodes.map((node) => (
              <button
                key={node.id}
                className={`stage-card ${statusClass(node.status)} ${selected?.id === node.id ? "selected" : ""} ${dependents.has(node.id) ? "dependent" : ""}`}
                onClick={() => choose(node)}
              >
                <i />
                <span>
                  <b>{node.title}</b>
                  <small>{label(node.status)}</small>
                </span>
                <em>→</em>
              </button>
            ))}
            {beatNodes.length > 0 && (
              <details className="beat-node-group">
                <summary>
                  <b>Individual beat images</b>
                  <small>{beatNodes.filter((node) => READY.has(node.status)).length}/{beatNodes.length} ready</small>
                </summary>
                {beatNodes.map((node) => (
                  <button
                    key={node.id}
                    className={`stage-card ${statusClass(node.status)} ${selected?.id === node.id ? "selected" : ""} ${dependents.has(node.id) ? "dependent" : ""}`}
                    onClick={() => choose(node)}
                  >
                    <i /><span><b>{node.title}</b><small>{label(node.status)}</small></span><em>→</em>
                  </button>
                ))}
              </details>
            )}
          </section>
        );
      })}
    </div>
  );
}

function DependencyGraph({ run, selected, choose, theme = "dark" }) {
  const light = theme === "light";
  const dependents = useMemo(
    () => dependentNodeIds(run.graph.edges, selected?.id),
    [run.graph.edges, selected?.id],
  );
  const flow = useMemo(() => {
    const phases = run.graph.phases || [],
      perPhase = {};
    return {
      nodes: run.graph.nodes.map((node) => {
        const phase = phases.indexOf(node.phase),
          row = perPhase[node.phase] || 0;
        perPhase[node.phase] = row + 1;
        return {
          id: node.id,
          type: "artifact",
          position: { x: Math.max(0, phase) * 255, y: row * 128 },
          data: {
            ...node,
            selected: selected?.id === node.id,
            dependent: dependents.has(node.id),
            previewBase: `/api/run/${run.job.job_id}/artifact`,
          },
        };
      }),
      edges: run.graph.edges.map((edge, index) => ({
        id: `${edge.source}-${edge.target}-${index}`,
        ...edge,
        animated:
          run.graph.nodes.find((node) => node.id === edge.target)?.status ===
          "RUNNING",
        style: {
          stroke: selected?.id === edge.source && dependents.has(edge.target)
            ? light ? "#6d3fd4" : "#b58cff"
            : edge.kind === "continuity"
              ? light ? "#2b5fc7" : "#4f8fc9"
              : edge.kind === "gate"
                ? light ? "#8a5f0b" : "#b58b4c"
                : light ? "#8a97a8" : "#53647d",
          strokeWidth: selected?.id === edge.source ? 2 : 1.2,
          strokeDasharray: edge.kind === "gate" ? "6 4" : undefined,
        },
      })),
    };
  }, [run, selected, dependents]);
  return (
    <div className="graph-shell">
      <ReactFlow
        nodes={flow.nodes}
        edges={flow.edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) =>
          choose(run.graph.nodes.find((item) => item.id === node.id))
        }
        defaultViewport={{ x: 24, y: 24, zoom: 0.62 }}
        minZoom={0.2}
        maxZoom={1.5}
      >
        <Background gap={24} color={light ? "#c9d3e1" : "#273246"} />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) =>
            node.data?.status === "RUNNING"
              ? light ? "#8a5f0b" : "#f2bb61"
              : node.data?.status === "DONE"
                ? light ? "#0c7a55" : "#38d996"
                : light ? "#8a97a8" : "#53647d"
          }
        />
      </ReactFlow>
    </div>
  );
}

function TextArtifacts({ base, items }) {
  const [chosen, setChosen] = useState(items[0]?.path || ""),
    [text, setText] = useState("");
  useEffect(() => {
    setChosen(items[0]?.path || "");
  }, [items.map((item) => item.path).join("|")]);
  useEffect(() => {
    if (!chosen) {
      setText("");
      return;
    }
    request(artifactUrl(base, chosen))
      .then((value) => setText(value.slice(0, 50000)))
      .catch(() => setText("Preview unavailable."));
  }, [base, chosen]);
  if (!items.length) return null;
  return (
    <section className="text-artifacts">
      <h3>Artifact contents</h3>
      {items.length > 1 && (
        <select
          value={chosen}
          onChange={(event) => setChosen(event.target.value)}
        >
          {items.map((item) => (
            <option key={item.path} value={item.path}>
              {item.path}
            </option>
          ))}
        </select>
      )}
      <pre>{text || "Loading…"}</pre>
    </section>
  );
}

function NodeDetail({ run, node, close, regenerate, fallbackAction, resolveFallback }) {
  if (!node)
    return (
      <aside className="detail empty">
        <span>↖</span>
        <h3>Select a stage</h3>
        <p>Inspect artifacts, execution metadata and regeneration impact.</p>
      </aside>
    );
  const base = `/api/run/${run.job.job_id}/artifact`;
  const existing = (node.artifacts || []).filter((item) => item.exists),
    media = existing.filter((item) => item.media),
    textItems = existing.filter((item) => !item.media);
  return (
    <aside className="detail">
      <button className="icon close" onClick={close} aria-label="Close detail">
        ×
      </button>
      <span className="eyebrow">
        {PHASE_LABELS[node.phase]} · {node.kind}
      </span>
      <h2>{node.title}</h2>
      <StatusPill status={node.status} />
      {node.description && <p className="description">{node.description}</p>}
      {node.validation && <p className="description" role="status">
        Image: {label(node.validation.status)} — {node.validation.reason}
      </p>}
      {node.validation?.references?.length > 0 && <section>
        <h3>References used</h3>
        <ol>{node.validation.references.map((ref, index) => <li key={`${index}-${ref.role}`}>
          {label(ref.role)} · {ref.path.split("/").pop()}
        </li>)}</ol>
      </section>}
      {media.length > 0 && (
        <div className="media-gallery">
          {media.map((item) => {
            const src = artifactUrl(base, item.path, item.updated_at);
            return (
              <div className="preview" key={item.path}>
                {/\.(png|jpe?g|webp)$/i.test(item.path) ? (
                  <img src={src} alt={`${node.title} preview`} />
                ) : /\.(mp4|mov|webm)$/i.test(item.path) ? (
                  <video controls preload="metadata" src={src} />
                ) : (
                  <audio controls preload="metadata" src={src} />
                )}
              </div>
            );
          })}
        </div>
      )}
      <section>
        <h3>
          Artifacts{" "}
          <span>
            {existing.length}/{node.artifacts?.length || 0}
          </span>
        </h3>
        {(node.artifacts || []).map((item) => (
          <a
            className={item.exists ? "" : "missing"}
            key={item.path}
            href={
              item.exists
                ? artifactUrl(base, item.path, item.updated_at)
                : undefined
            }
            target="_blank"
            rel="noreferrer"
          >
            <i>{item.exists ? "✓" : "—"}</i>
            <span>
              {item.path}
              <small>
                {item.exists ? formatBytes(item.bytes) : "not generated"}
              </small>
            </span>
          </a>
        ))}
      </section>
      <TextArtifacts base={base} items={textItems} />
      {Object.keys(node.meta || {}).length > 0 && (
        <section>
          <h3>Execution</h3>
          <dl>
            {Object.entries(node.meta)
              .filter(([key]) => !["command"].includes(key))
              .slice(0, 12)
              .map(([key, value]) => (
                <React.Fragment key={key}>
                  <dt>{label(key)}</dt>
                  <dd>
                    {typeof value === "object"
                      ? JSON.stringify(value)
                      : String(value)}
                  </dd>
                </React.Fragment>
              ))}
          </dl>
        </section>
      )}
      {fallbackAction?.visible_stage === node.id && (
        <section className="fallback-action">
          <span className="eyebrow">ACTION REQUIRED</span>
          <h3>ChatGPT could not complete this step</h3>
          <p>Approve Gemini to retry this exact request with its same references, or retry ChatGPT without fallback. Completed work remains reused.</p>
          <div>
            <button className="primary" disabled={run.job.live} onClick={() => resolveFallback("approve")}>Approve Gemini fallback</button>
            <button className="secondary" disabled={run.job.live} onClick={() => resolveFallback("retry_primary")}>Retry ChatGPT</button>
          </div>
        </section>
      )}
      <button
        className="primary"
        disabled={run.job.live || run.job.read_only || node.regeneratable === false}
        onClick={() => regenerate(node)}
      >
        {node.regeneratable === false
          ? "Managed automatically by the pipeline"
          : run.job.read_only
          ? "External run · inspection only"
          : run.job.live
            ? "Wait for the active run to finish"
            : "Regenerate this stage →"}
      </button>
    </aside>
  );
}

function RegenerationModal({ run, node, close, started }) {
  const [plan, setPlan] = useState(null),
    [feedback, setFeedback] = useState(""),
    [useChatgptFeedback, setUseChatgptFeedback] = useState(false),
    [isolated, setIsolated] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const supportsIsolated = (node.regeneration?.modes || []).includes("isolated");
  const supportsChatgptFeedback = node.id.startsWith("beat_image_") && ["q_station", "question_harvest"].includes(run.job.content_project);
  useEffect(() => {
    setPlan(null);
    setError("");
    request("/api/regenerations/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: run.job.job_id,
        node_ids: [node.id],
        regeneration_mode: isolated ? "isolated" : "cascade",
      }),
    })
      .then(setPlan)
      .catch((failure) => setError(failure.message));
  }, [run.job.job_id, node.id, isolated]);
  useEffect(() => {
    const escape = (event) => event.key === "Escape" && close();
    addEventListener("keydown", escape);
    return () => removeEventListener("keydown", escape);
  }, [close]);
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const response = await request("/api/regenerations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: run.job.job_id,
          node_ids: [node.id],
          feedback,
          use_chatgpt_feedback: supportsChatgptFeedback && useChatgptFeedback,
          regeneration_mode: isolated ? "isolated" : "cascade",
        }),
      });
      started(response);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className="modal-back"
      role="dialog"
      aria-modal="true"
      aria-labelledby="regeneration-title"
      onMouseDown={(event) => event.target === event.currentTarget && close()}
    >
      <form className="modal impact-modal" onSubmit={submit}>
        <button
          type="button"
          className="icon close"
          onClick={close}
          aria-label="Close"
        >
          ×
        </button>
        <span className="eyebrow">SAFE REGENERATION</span>
        <h2 id="regeneration-title">{node.title}</h2>
        <p>{isolated
          ? "Only this source image will be regenerated. Later beat images stay byte-for-byte unchanged; transition metadata and final renders still rebuild to use the new image."
          : "The selected stage and every data-dependent descendant will be versioned and rebuilt. Everything else stays reusable."
        }</p>
        {supportsIsolated && (
          <label className="toggle-field regeneration-mode">
            <input
              type="checkbox"
              checked={isolated}
              onChange={(event) => setIsolated(event.target.checked)}
            />
            <span className="switch" />
            <span>
              <b>Keep all other beat images unchanged</b>
              <small>Overrides the normal continuity cascade. Use this for a precise one-image correction.</small>
            </span>
          </label>
        )}
        {plan ? (
          <div className="impact-grid">
            <section>
              <h3>Regenerate · {plan.affected_nodes.length}</h3>
              <div>
                {plan.affected_nodes.map((id) => (
                  <span key={id}>{plan.nodes[id]?.title || label(id)}</span>
                ))}
              </div>
            </section>
            <section>
              <h3>Reuse · {plan.reused_nodes.length}</h3>
              <div>
                {plan.reused_nodes.map((id) => (
                  <span key={id}>{plan.nodes[id]?.title || label(id)}</span>
                ))}
              </div>
            </section>
          </div>
        ) : (
          !error && (
            <div className="loading-line">Calculating dependency impact…</div>
          )
        )}
        <label className="field">
          <span>
            Revision note <i>{isolated || useChatgptFeedback ? "required" : "optional"}</i>
          </span>
          <textarea
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            maxLength={4000}
            required={isolated || useChatgptFeedback}
            placeholder="Describe exactly what should change in this image. This is added to the provider prompt."
          />
        </label>
        {supportsChatgptFeedback && (
          <label className="toggle-field regeneration-mode">
            <input
              type="checkbox"
              checked={useChatgptFeedback}
              onChange={(event) => setUseChatgptFeedback(event.target.checked)}
            />
            <span className="switch" />
            <span>
              <b>Use ChatGPT feedback before regenerating</b>
              <small>ChatGPT reviews the current image and your note once, then Gemini creates the replacement. The replacement is not sent back to ChatGPT.</small>
            </span>
          </label>
        )}
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" disabled={busy || !plan || !plan.can_start || ((isolated || useChatgptFeedback) && !feedback.trim())}>
          {busy
            ? "Preparing revision…"
            : plan?.can_start === false
              ? plan?.read_only
                ? "External run · inspection only"
                : "Another run is active"
              : `Confirm ${plan?.affected_nodes.length || ""} affected stages`}
        </button>
      </form>
    </div>
  );
}

function TransitionOverrides({ timeline, values, overrides, onChange }) {
  const beats = Array.isArray(timeline?.beats) ? timeline.beats : [];
  const byBoundary = new Map((overrides || []).map((item) => [`${item.from_beat_id}→${item.to_beat_id}`, item]));
  const defaultType = values.motion_transition_default_type || "fade";
  const defaultSeconds = Number(values.motion_transition_seconds) || .28;
  const replace = (boundary, next) => {
    const key = `${boundary.from_beat_id}→${boundary.to_beat_id}`;
    const remainder = (overrides || []).filter((item) => `${item.from_beat_id}→${item.to_beat_id}` !== key);
    onChange([...remainder, next]);
  };
  if (!beats.length) {
    return <section className="transition-overrides empty"><b>Exact boundary overrides</b><small>Available after the timeline is built for this run.</small></section>;
  }
  return (
    <section className="transition-overrides">
      <header>
        <div><b>Exact boundary overrides</b><small>Manual rows always win over AI and the global default.</small></div>
        <span>{beats.length - 1} boundaries</span>
      </header>
      {beats.slice(1).map((to, index) => {
        const from = beats[index];
        const id = `${from.beat_id}→${to.beat_id}`;
        const saved = byBoundary.get(id);
        const type = saved?.type || defaultType;
        const seconds = saved?.duration ?? (type === "cut" ? 0 : defaultSeconds);
        const name = (beat) => `${beat.media_type === "video" ? "Video" : "Image"} ${String(beat.beat_id).replace(/^video_/, "")}`;
        return <div className="transition-row" key={id}>
          <span className="transition-boundary">{name(from)} <i>→</i> {name(to)}</span>
          <select value={type} onChange={(event) => replace({ from_beat_id: String(from.beat_id), to_beat_id: String(to.beat_id) }, { from_beat_id: String(from.beat_id), to_beat_id: String(to.beat_id), type: event.target.value, duration: event.target.value === "cut" ? 0 : seconds })}>
            {TRANSITION_OPTIONS.map(([value, title]) => <option value={value} key={value}>{title}</option>)}
          </select>
          <input aria-label={`Transition seconds ${id}`} type="number" min="0.08" max="0.45" step="0.01" disabled={type === "cut"} value={type === "cut" ? 0 : seconds} onChange={(event) => replace({ from_beat_id: String(from.beat_id), to_beat_id: String(to.beat_id) }, { from_beat_id: String(from.beat_id), to_beat_id: String(to.beat_id), type, duration: Number(event.target.value) })} />
          {saved ? <button type="button" onClick={() => onChange((overrides || []).filter((item) => `${item.from_beat_id}→${item.to_beat_id}` !== id))}>Reset</button> : <small>Default</small>}
        </div>;
      })}
    </section>
  );
}

function ConfigModal({ run, close, done }) {
  const [schema, setSchema] = useState(null),
    [values, setValues] = useState(null),
    [plan, setPlan] = useState(null),
    [styles, setStyles] = useState([]),
    [characters, setCharacters] = useState([]),
    [styleReference, setStyleReference] = useState(null),
    [logoAsset, setLogoAsset] = useState(null),
    [musicAsset, setMusicAsset] = useState(null),
    [narrationAsset, setNarrationAsset] = useState(null),
    [stylesLoading, setStylesLoading] = useState(false),
    [timeline, setTimeline] = useState(null),
    [timelineTried, setTimelineTried] = useState(false),
    [openGroups, setOpenGroups] = useState(new Set(["visual"])),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [transitionOverrides, setTransitionOverrides] = useState([]),
    [uploadedFonts, setUploadedFonts] = useState([]),
    initialValues = useRef(null);
  const addUploadedFont = (font) => setUploadedFonts((current) => current.some((item) => item.family === font.family) ? current : [...current, font]);
  const isDirty = (current) => {
    if (!current || !initialValues.current) return false;
    const { transition_overrides: _a, ...restCurrent } = { ...current, transition_overrides: transitionOverrides };
    const { transition_overrides: _b, ...restInitial } = initialValues.current;
    return JSON.stringify(restCurrent) !== JSON.stringify(restInitial)
      || JSON.stringify(transitionOverrides) !== JSON.stringify(initialValues.current.transition_overrides || []);
  };
  const requestClose = () => {
    if (!isDirty(values) || window.confirm("Discard unapplied revision edits?")) close();
  };
  useEffect(() => {
    Promise.all([
      request(`/api/run/${run.job.job_id}/config`),
      request("/api/launch-schema"),
    ])
      .then(([data, contract]) => {
        setValues(data.values);
        initialValues.current = {
          ...data.values,
          transition_overrides: Array.isArray(data.transition_overrides) ? data.transition_overrides : [],
        };
        setStyleReference(data.style_reference && typeof data.style_reference === "object" ? data.style_reference : null);
        setLogoAsset(data.logo_asset && typeof data.logo_asset === "object" ? data.logo_asset : null);
        setMusicAsset(data.music_asset && typeof data.music_asset === "object" ? data.music_asset : null);
        setNarrationAsset(data.narration_asset && typeof data.narration_asset === "object" ? data.narration_asset : null);
        setTransitionOverrides(Array.isArray(data.transition_overrides) ? data.transition_overrides : []);
        setSchema(contract.schema);
      })
      .catch((failure) => setError(failure.message));
  }, [run.job.job_id]);
  useEffect(() => {
    if (!values?.content_project) return;
    let cancelled = false;
    setStylesLoading(true);
    Promise.all([
      request(`/api/style-catalog?content_project=${encodeURIComponent(values.content_project)}`),
      request(`/api/character-catalog?content_project=${encodeURIComponent(values.content_project)}`),
    ])
      .then(([styleData, characterData]) => {
        if (cancelled) return;
        setStyles(styleData.styles || []);
        setCharacters(characterData.characters || []);
      })
      .catch((failure) => !cancelled && setError(failure.message))
      .finally(() => !cancelled && setStylesLoading(false));
    return () => { cancelled = true; };
  }, [values?.content_project]);
  useEffect(() => {
    let cancelled = false;
    setTimeline(null);
    setTimelineTried(false);
    const loadTimeline = (retry) =>
      request(`/api/run/${run.job.job_id}/timeline`)
        .then((data) => {
          if (cancelled) return;
          const parsed = data && typeof data === "object" ? data.timeline : null;
          setTimeline(parsed && typeof parsed === "object" ? parsed : null);
          setTimelineTried(true);
        })
        .catch(() => {
          if (cancelled) return;
          if (retry) setTimeout(() => !cancelled && loadTimeline(false), 2500);
          else {
            setTimeline(null);
            setTimelineTried(true);
          }
        });
    loadTimeline(true);
    return () => {
      cancelled = true;
    };
  }, [run.job.job_id]);
  const subtitleBeats = useMemo(() => {
    const beats = timeline?.beats;
    if (!Array.isArray(beats) || !beats.length) return [];
    const cues = Array.isArray(timeline?.subtitles) ? timeline.subtitles : [];
    const recordedWords = cues.flatMap((cue) => Array.isArray(cue?.words) ? cue.words : []);
    const projectedCues = recordedWords.length
      ? previewCuesFromWords(recordedWords, values?.subtitle_max_words)
      : cues;
    const base = `/api/run/${run.job.job_id}/artifact`;
    const beatById = new Map(beats.filter(Boolean).map((beat) => [String(beat.beat_id), beat]));
    const ownerFor = (cue) => {
      const direct = beatById.get(String(cue?.beat_id));
      if (direct) return direct;
      const start = Number(cue?.start);
      const end = Number(cue?.end);
      if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
      const midpoint = (start + end) / 2;
      return beats.reduce((best, beat) => {
        if (!beat) return best;
        const beatStart = Number(beat.start) || 0;
        const beatEnd = Number(beat.end) || beatStart;
        const overlap = Math.max(0, Math.min(end, beatEnd) - Math.max(start, beatStart));
        const contains = midpoint >= beatStart && midpoint <= beatEnd ? 1 : 0;
        const distance = midpoint < beatStart ? beatStart - midpoint : midpoint > beatEnd ? midpoint - beatEnd : 0;
        const candidate = { beat, overlap, contains, distance };
        if (!best) return candidate;
        if (candidate.overlap !== best.overlap) return candidate.overlap > best.overlap ? candidate : best;
        if (candidate.contains !== best.contains) return candidate.contains > best.contains ? candidate : best;
        return candidate.distance < best.distance ? candidate : best;
      }, null)?.beat || null;
    };
    return projectedCues
      .filter((cue) => cue && (cue.ass_text || cue.text))
      .map((cue) => {
        const beat = ownerFor(cue);
        if (!beat || !(beat.image || beat.source)) return null;
        const raw = String(cue.ass_text || cue.text).replace(/\\N/g, "\n");
        return {
          beat_id: beat.beat_id,
          kind: beat.media_type === "video" ? "video" : "image",
          src: `${base}/${beat.image || beat.source}`,
          mediaStart: Math.max(0, (Number(cue.start) || 0) - (Number(beat.start) || 0)),
          start: Number(cue.start) || 0,
          lines: raw.split("\n").filter(Boolean),
        };
      })
      .filter(Boolean);
  }, [timeline, values?.subtitle_max_words, run.job.job_id]);
  const brandingFrames = useMemo(() => {
    const base = `/api/run/${run.job.job_id}/artifact`;
    // Ten evenly distributed timeline representatives make opening clips and
    // body-image beats inspectable without loading a full contact sheet at once.
    return previewFramesFromTimeline(timeline, base, 10);
  }, [timeline, run.job.job_id]);
  useEffect(() => {
    if (!values) return;
    let cancelled = false;
    setPlan(null);
    const timer = setTimeout(() => {
      request("/api/config-revisions/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: run.job.job_id, values, transition_overrides: transitionOverrides }),
      })
        .then((data) => {
          if (!cancelled) {
            setPlan(data);
            setError("");
          }
        })
        .catch((failure) => !cancelled && setError(failure.message));
    }, 250);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [run.job.job_id, values, transitionOverrides]);
  useEffect(() => {
    const escape = (event) => event.key === "Escape" && requestClose();
    addEventListener("keydown", escape);
    return () => removeEventListener("keydown", escape);
  });
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      validateLaunchValues(values);
      const response = await request("/api/config-revisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: run.job.job_id,
          config: { values, transition_overrides: transitionOverrides },
        }),
      });
      done(response);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div
      className="modal-back"
      role="dialog"
      aria-modal="true"
      aria-labelledby="config-title"
      onMouseDown={(event) => event.target === event.currentTarget && requestClose()}
    >
      <form className="modal config-modal" onSubmit={submit}>
        <button
          type="button"
          className="icon close"
          onClick={requestClose}
          aria-label="Close"
        >
          ×
        </button>
        <span className="eyebrow">VERSIONED RUN SETTINGS</span>
        <h2 id="config-title">Revise this run safely</h2>
        <p>
          Edit the same controls used at launch. The impact preview identifies exactly
          which stages rebuild before any files are changed. Changing the topic launches
          a separate run and keeps this one intact.
        </p>
        <div className="frozen-project">
          <span>Content project</span>
          <b>{label(values?.content_project || run.job.content_project)}</b>
          <small>Fixed for this run</small>
        </div>
        {schema && values ? (
          <div className="config-fields">
            {schema.groups
              .filter((group) => !group.projects || group.projects.includes(values.content_project))
              .map((group) => ({
                ...group,
                fields: group.fields.filter(
                  (field) => field.type !== "readonly" && field.name !== "content_project",
                ),
              }))
              .filter((group) => group.fields.length)
              .map((group) => (
                <SettingsGroup
                  key={group.id}
                  group={group}
                  values={values}
                  change={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
                  replaceGroup={(settings) => setValues((current) => ({ ...current, ...settings }))}
                  styles={styles}
                  characters={characters}
                  stylesLoading={stylesLoading}
                  styleReferencePreview={styleReference?.preview_path ? `/api/run/${run.job.job_id}/artifact/${styleReference.preview_path}` : ""}
                  logoPreviewUrl={logoAsset?.preview_path ? `/api/run/${run.job.job_id}/artifact/${logoAsset.preview_path}` : ""}
                  musicPreviewUrl={musicAsset?.preview_path ? `/api/run/${run.job.job_id}/artifact/${musicAsset.preview_path}` : ""}
                  narrationPreviewUrl={narrationAsset?.preview_path ? `/api/run/${run.job.job_id}/artifact/${narrationAsset.preview_path}` : ""}
                  open={openGroups.has(group.id)}
                  toggle={() => setOpenGroups((current) => {
                    const next = new Set(current);
                    next.has(group.id) ? next.delete(group.id) : next.add(group.id);
                    return next;
                  })}
                  subtitleBackdrops={[
                    `/api/run/${run.job.job_id}/artifact/references/world_keyframe.png`,
                    ...styles.map((item) => item.anchor_url),
                  ].filter((url, index, all) => url && all.indexOf(url) === index)}
                  subtitleBackdropLabel="This run's world keyframe"
                  subtitleBeats={subtitleBeats}
                  timelineBeats={
                    timelineTried
                      ? Array.isArray(timeline?.beats)
                        ? timeline.beats.length
                        : 0
                      : -1
                  }
                  subtitleNote={
                    timelineTried && !subtitleBeats.length
                      ? "static sample — this run has no timeline yet"
                      : ""
                  }
                  brandingFrames={brandingFrames}
                  brandingBackdropLabel={timelineTried ? "Timeline preview unavailable" : "Loading timeline frames…"}
                  uploadedFonts={uploadedFonts}
                  onFontUploaded={addUploadedFont}
                />
              ))}
            <TransitionOverrides timeline={timeline} values={values} overrides={transitionOverrides} onChange={setTransitionOverrides} />
          </div>
        ) : !error && <div className="loading-line">Loading frozen settings…</div>}
        {plan && (
          <div className="config-review">
            <div className="change-summary">
              <span>{plan.changed_fields.length} changed setting(s)</span>
              {plan.changed_fields.map((name) => <b key={name}>{label(name)}</b>)}
            </div>
            {plan.new_run ? (
              <div className="topic-change-notice">
                Topic changed: this will launch a new, independent run. No files or
                stages from the current run will be reused.
              </div>
            ) : (
              <>
              {plan.changed_fields.some((name) => ["character_mode", "character_id"].includes(name)) && (
                <div className="topic-change-notice">
                  Character change: the previous character/presentation branch will be archived,
                  then script, intro media and every dependent stage will rebuild in this run.
                </div>
              )}
              <div className="impact-grid config-impact">
                <section>
                  <h3>Rebuild · {plan.affected_nodes.length}</h3>
                  <div>{plan.affected_nodes.map((id) => <span key={id}>{label(id)}</span>)}</div>
                </section>
                <section>
                  <h3>Reuse · {plan.reused_nodes.length}</h3>
                  <div>{plan.reused_nodes.map((id) => <span key={id}>{label(id)}</span>)}</div>
                </section>
              </div>
              </>
            )}
          </div>
        )}
        {error && <div className="inline-error" role="alert">{error}</div>}
        <button
          className="primary"
          disabled={busy || !values || !plan || !plan.changed_fields.length || !plan.can_start}
        >
          {busy
            ? "Applying changes…"
            : plan?.can_start === false
              ? plan?.read_only ? "External run · inspection only" : "Another run is active"
              : plan?.new_run
                ? "Launch separate run →"
                : `Apply ${plan?.changed_fields?.length || 0} change(s) safely`}
        </button>
      </form>
    </div>
  );
}

function ActivityPanel({ events, log, open, toggle }) {
  const recent = [...events].reverse().slice(0, 30);
  return (
    <section className={`activity-drawer ${open ? "open" : ""}`}>
      <button className="activity-handle" onClick={toggle} aria-expanded={open}>
        <span>
          <i />
          Live activity
        </span>
        <b>{open ? "Close" : `${recent.length} events`}</b>
      </button>
      {open && (
        <div className="activity-body">
          <div className="event-list">
            {recent.map((event) => (
              <div className="event" key={event.id}>
                <i className={statusClass(event.status)} />
                <div>
                  <b>{label(event.stage)}</b>
                  <span>
                    {label(event.status)}
                    {event.message ? ` · ${event.message}` : ""}
                  </span>
                </div>
                <time>
                  {event.at
                    ? new Date(event.at).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })
                    : ""}
                </time>
              </div>
            ))}
          </div>
          <pre className="live-log">{log || "Waiting for runner output…"}</pre>
        </div>
      )}
    </section>
  );
}

const RELEASE_DEFAULTS = {
  generate_metadata: true,
  generate_thumbnail: true,
  create_upload_guide: true,
  send_telegram: true,
  force: false,
  metadata_note: "",
  thumbnail_note: "",
  title_override: "",
  thumbnail: {
    count_mode: "fixed", count: 3, auto_min: 2, auto_max: 4, concept_count: "auto",
    diversity: "high", layout_mode: "auto", allowed_layouts: ["character_left", "character_right", "contrast_split", "discovery_focus"],
    tension: "strong", brand_profile: "q_station_v1", aspect_ratio: "9:16", image_model: "inherit_episode", quality: "native", image_fallback: "off",
    thumbnail_note: "", must_include: "", must_avoid: "", text_mode: "auto", manual_text: "", font_id: "montserrat_bold",
    case_mode: "auto", text_position: "auto", max_words: 6, max_lines: 3, text_max_scale: .15, text_fill: "#FFFFFF", text_outline: "#111827", outline_width: .012, shadow: true, text_background: true, corrections_per_candidate: 1, max_image_generations: 6,
    review_preset: "balanced", review_enabled: true, export_format: "png", preview_small: true, comparison_sheet: true, send_comparison_sheet: true,
    send_report_json: true, send_raw_artwork: false, delivery_mode: "all_final_candidates", resend: false,
  },
};

function ReleaseModal({ jobId, close, started }) {
  const [settings, setSettings] = useState(RELEASE_DEFAULTS);
  const [capabilities, setCapabilities] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const change = (name, value) => setSettings((current) => ({ ...current, [name]: value }));
  const thumb = (name, value) => setSettings((current) => ({ ...current, thumbnail: { ...current.thumbnail, [name]: value } }));
  useEffect(() => {
    let active = true;
    Promise.all([request("/api/release-schema"), request("/api/release-settings")]).then(([schema, saved]) => {
      if (!active || !schema?.defaults) return;
      setCapabilities(schema.capabilities || null);
      setSettings(saved?.settings || schema.defaults);
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  const tasks = [
    ["generate_metadata", "Generate YouTube metadata", "Creates title alternatives, description, tags, upload recommendations, and a thumbnail brief."],
    ["generate_thumbnail", "Generate thumbnail candidates", "Creates independent text-free artworks, composites real English text locally, reviews final files, and recommends one."],
    ["create_upload_guide", "Create upload guide", "Writes copy-ready YouTube instructions and manual-review reminders."],
    ["send_telegram", "Send release files to Telegram", "Always sends the QC-passed master and every visible final thumbnail candidate as original documents."],
  ];
  async function submit(event) {
    event.preventDefault();
    if (!tasks.some(([key]) => settings[key])) {
      setError("Choose at least one Release step.");
      return;
    }
    setBusy(true); setError("");
    try {
      const response = await request("/api/releases", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, settings }),
      });
      started(response);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="release-title" onMouseDown={(event) => event.target === event.currentTarget && !busy && close()}>
      <form className="modal release-modal" onSubmit={submit}>
        <button type="button" className="icon close" onClick={close} disabled={busy} aria-label="Close Release settings">×</button>
        <span className="eyebrow">POST-RENDER RELEASE</span>
        <h2 id="release-title">Choose Release steps</h2>
        <p>Only selected operations run. The finished video is never changed; this creates its YouTube package and optional delivery.</p>
        <section className="release-step-list" aria-label="Release operations">
          {tasks.map(([key, title, detail]) => (
            <label className="toggle-field" key={key}>
              <input type="checkbox" checked={settings[key]} onChange={(event) => change(key, event.target.checked)} disabled={busy} />
              <span className="switch" />
              <span><b>{title}</b><small>{detail}</small></span>
            </label>
          ))}
        </section>
        <section className="release-editorial">
          <h3>Basic</h3>
          <label className="field">
            <span>Custom final title</span>
            <input value={settings.title_override} maxLength="100" placeholder="Leave empty to use generated or saved metadata" disabled={busy} onChange={(event) => change("title_override", event.target.value)} />
            <small>Applied to the metadata, upload guide, and Telegram caption.</small>
          </label>
          <label className="field">
            <span>Metadata direction</span>
            <textarea value={settings.metadata_note} maxLength="2000" placeholder="Facts, tone, audience, wording to avoid, or other editorial direction…" disabled={busy} onChange={(event) => change("metadata_note", event.target.value)} />
            <small>Used only when generating metadata; it cannot override the source facts.</small>
          </label>
          <label className="field">
            <span>Candidate count</span>
            <select value={settings.thumbnail.count_mode} disabled={busy || !settings.generate_thumbnail} onChange={(event) => thumb("count_mode", event.target.value)}><option value="fixed">Fixed</option><option value="auto">Auto within range</option></select>
            {settings.thumbnail.count_mode === "fixed" ? <input type="number" min="1" max="6" value={settings.thumbnail.count} disabled={busy || !settings.generate_thumbnail} onChange={(event) => thumb("count", Number(event.target.value))} /> : <span className="field-grid"><input aria-label="Minimum candidates" type="number" min="1" max="6" value={settings.thumbnail.auto_min} onChange={(event) => thumb("auto_min", Number(event.target.value))} /><input aria-label="Maximum candidates" type="number" min="1" max="6" value={settings.thumbnail.auto_max} onChange={(event) => thumb("auto_max", Number(event.target.value))} /></span>}
            <small>{settings.thumbnail.count_mode === "fixed" ? `${settings.thumbnail.count} independent final candidates` : `${settings.thumbnail.auto_min}–${settings.thumbnail.auto_max} independently planned candidates`}; all visible final candidates are delivered.</small>
          </label>
          <label className="field"><span>Layout family</span><select value={settings.thumbnail.layout_mode} disabled={busy || !settings.generate_thumbnail} onChange={(event) => thumb("layout_mode", event.target.value)}><option value="auto">Auto — diverse layouts</option><option value="character_left">Character left</option><option value="character_right">Character right</option><option value="contrast_split">Contrast split</option><option value="discovery_focus">Discovery focus</option></select></label>
          <label className="field"><span>Text</span><select value={settings.thumbnail.text_mode} disabled={busy || !settings.generate_thumbnail} onChange={(event) => thumb("text_mode", event.target.value)}><option value="auto">Auto from the factual release brief</option><option value="manual">One manual headline</option></select>{settings.thumbnail.text_mode === "manual" && <input value={settings.thumbnail.manual_text} maxLength="40" placeholder="2–6 English words" onChange={(event) => thumb("manual_text", event.target.value)} />}</label>
          <label className="field">
            <span>Thumbnail art direction</span>
            <textarea value={settings.thumbnail.thumbnail_note} maxLength="2000" placeholder="Desired visual emphasis, factual scene, composition, or constraints…" disabled={busy || !settings.generate_thumbnail} onChange={(event) => thumb("thumbnail_note", event.target.value)} />
            <small>Gemini creates artwork without text. The final headline, badge, and frame are rendered locally and reviewed on the final file.</small>
          </label>
        </section>
        <details className="release-editorial"><summary><b>Advanced thumbnail settings</b></summary><div className="field-grid">
          <label className="field"><span>Tension</span><select value={settings.thumbnail.tension} onChange={(event) => thumb("tension", event.target.value)}><option value="restrained">Restrained</option><option value="strong">Strong</option><option value="dramatic">Dramatic</option></select></label>
          <label className="field"><span>Diversity</span><select value={settings.thumbnail.diversity} onChange={(event) => thumb("diversity", event.target.value)}><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></label>
          <label className="field"><span>Final reviewer</span><select value={settings.thumbnail.review_preset} onChange={(event) => thumb("review_preset", event.target.value)}><option value="balanced">Balanced</option><option value="clarity_first">Clarity first</option><option value="brand_first">Brand first</option></select></label>
          <label className="field"><span>Font</span><select value={settings.thumbnail.font_id} onChange={(event) => thumb("font_id", event.target.value)}>{(capabilities?.fonts || [{ id: "montserrat_bold", name: "Montserrat Bold" }]).map((font) => <option value={font.id} key={font.id}>{font.name}</option>)}</select></label>
          <label className="field"><span>Text case</span><select value={settings.thumbnail.case_mode} onChange={(event) => thumb("case_mode", event.target.value)}><option value="auto">Auto</option><option value="uppercase">Uppercase</option><option value="sentence_case">Sentence case</option></select></label>
          <label className="field"><span>Text size</span><input type="range" min="0.08" max="0.2" step="0.005" value={settings.thumbnail.text_max_scale} onChange={(event) => thumb("text_max_scale", Number(event.target.value))} /><small>{Math.round(settings.thumbnail.text_max_scale * 100)}% of canvas width; layout may reduce only when needed to fit.</small></label>
          <label className="field"><span>Text fill</span><input type="color" value={settings.thumbnail.text_fill} onChange={(event) => thumb("text_fill", event.target.value.toUpperCase())} /></label>
          <label className="field"><span>Outline color</span><input type="color" value={settings.thumbnail.text_outline} onChange={(event) => thumb("text_outline", event.target.value.toUpperCase())} /></label>
          <label className="field"><span>Outline thickness</span><input type="range" min="0" max="0.04" step="0.002" value={settings.thumbnail.outline_width} onChange={(event) => thumb("outline_width", Number(event.target.value))} /><small>{Math.round(settings.thumbnail.outline_width * 1000) / 10}% of canvas width</small></label>
          <label className="field"><span>Text position</span><select value={settings.thumbnail.text_position} onChange={(event) => thumb("text_position", event.target.value)}><option value="auto">Auto</option><option value="top">Top</option><option value="bottom">Bottom</option><option value="left">Left</option><option value="right">Right</option></select></label>
          <label className="field"><span>Quality corrections per candidate</span><input type="number" min="0" max="2" value={settings.thumbnail.corrections_per_candidate} onChange={(event) => thumb("corrections_per_candidate", Number(event.target.value))} /></label>
          <label className="field"><span>Maximum image submissions</span><input type="number" min="1" max="18" value={settings.thumbnail.max_image_generations} onChange={(event) => thumb("max_image_generations", Number(event.target.value))} /></label>
          <label className="field"><span>Image-generation fallback</span><select value={settings.thumbnail.image_fallback} onChange={(event) => thumb("image_fallback", event.target.value)}><option value="off">Off — Gemini only</option><option value="chatgpt_on_gemini_failure">ChatGPT if Gemini fails</option></select><small>Explicit fallback only. The release receipt records the Gemini error and actual producing provider.</small></label>
          <label className="field"><span>Must include</span><input maxLength="500" value={settings.thumbnail.must_include || ""} onChange={(event) => thumb("must_include", event.target.value)} /></label>
          <label className="field"><span>Must avoid</span><input maxLength="500" value={settings.thumbnail.must_avoid || ""} onChange={(event) => thumb("must_avoid", event.target.value)} /></label>
        </div><label className="toggle-field"><input type="checkbox" checked={settings.thumbnail.text_background} onChange={(event) => thumb("text_background", event.target.checked)} /><span className="switch" /><span><b>Text background</b><small>Adds a restrained translucent dark panel behind the headline for small-screen readability.</small></span></label><label className="toggle-field"><input type="checkbox" checked={settings.thumbnail.shadow} onChange={(event) => thumb("shadow", event.target.checked)} /><span className="switch" /><span><b>Text shadow</b><small>Preserves contrast over detailed artwork.</small></span></label><label className="toggle-field"><input type="checkbox" checked={settings.thumbnail.review_enabled} onChange={(event) => thumb("review_enabled", event.target.checked)} /><span className="switch" /><span><b>Run thumbnail QC and final visual review</b><small>When off, Gemini artwork is not sent to ChatGPT for image QC or final-thumbnail review. File decoding, dimensions, font rendering, and text bounds still run locally; the recommendation is marked as skipped.</small></span></label><small>Default typography is Montserrat Bold, white fill, dark outline, shadow, and a subtle background for clear small-screen reading. Actual supported ratio: 9:16.</small></details>
        <details className="release-editorial"><summary><b>Delivery</b></summary>
          <label className="toggle-field"><input type="checkbox" checked={settings.thumbnail.send_comparison_sheet} onChange={(event) => thumb("send_comparison_sheet", event.target.checked)} /><span className="switch" /><span><b>Send comparison sheet</b><small>Preview only; original candidates are always sent as documents.</small></span></label>
          <label className="toggle-field"><input type="checkbox" checked={settings.thumbnail.send_report_json} onChange={(event) => thumb("send_report_json", event.target.checked)} /><span className="switch" /><span><b>Send selection report</b><small>Contains the reviewer recommendation and final-file hashes.</small></span></label>
          <p className="release-dependency">Delivery mode: <b>all final candidates</b> (locked for this release version). A reviewer recommendation is editorial guidance, not a YouTube A/B test.</p>
        </details>
        <label className="toggle-field release-force">
          <input type="checkbox" checked={settings.force} onChange={(event) => change("force", event.target.checked)} disabled={busy} />
          <span className="switch" />
          <span><b>Replace already completed selected outputs</b><small>Use for an intentional new metadata or thumbnail version. Existing files remain in the project history where retained.</small></span>
        </label>
        <small className="release-dependency">Start summary: {settings.generate_thumbnail ? `${settings.thumbnail.count_mode === "fixed" ? settings.thumbnail.count : `${settings.thumbnail.auto_min}–${settings.thumbnail.auto_max}`} candidates, up to ${settings.thumbnail.max_image_generations} image submissions, ${settings.thumbnail.image_model}, ${settings.thumbnail.aspect_ratio}; every visible final candidate is sent when Telegram delivery is on.` : "Thumbnail generation is off: no thumbnail provider call or thumbnail preflight runs."} If Metadata is off, dependent steps reuse saved metadata and stop before any provider call when it is unavailable.</small>
        {error && <div className="inline-error" role="alert">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? "Starting Release…" : "Start selected Release steps →"}</button>
      </form>
    </div>
  );
}

function RunPage({ jobId, goHome, goRun, notify, theme, onToggleTheme }) {
  const [run, setRun] = useState(null),
    [selected, setSelected] = useState(null),
    [view, setView] = useState("board"),
    [revisionNode, setRevisionNode] = useState(null),
    [configOpen, setConfigOpen] = useState(false),
    [releaseOpen, setReleaseOpen] = useState(false),
    [drawer, setDrawer] = useState(true),
    [log, setLog] = useState(""),
    [autoUpdate, setAutoUpdate] = useState(readAutoUpdate),
    [connStatus, setConnStatus] = useState("connecting"),
    [error, setError] = useState("");
  const seen = useRef(new Set()),
    offset = useRef(0),
    initialized = useRef(false),
    hasRun = useRef(false),
    disconnected = useRef(false),
    loading = useRef(false);
  const load = async () => {
    if (loading.current) return;
    loading.current = true;
    try {
      const data = normalizeRunPayload(await request(`/api/run/${jobId}/graph`));
      const incoming = data.activity || [];
      if (initialized.current)
        incoming.forEach((event) => {
          if (
            !seen.current.has(event.id) &&
            ["DONE", "REUSED", "FAILED", "MISSING"].includes(event.status)
          )
            notify(
              event.status === "DONE"
                ? "Stage complete"
                : event.status === "REUSED"
                  ? "Stage reused"
                  : "Stage needs attention",
              label(event.stage),
              ["DONE", "REUSED"].includes(event.status) ? "" : "bad",
            );
        });
      incoming.forEach((event) => seen.current.add(event.id));
      initialized.current = true;
      hasRun.current = true;
      setRun(data);
      setSelected(
        (current) =>
          data.graph.nodes.find((node) => node.id === current?.id) || null,
      );
      setError("");
      const tail = await request(`/api/log/${jobId}?offset=${offset.current}`);
      offset.current = tail.offset;
      if (tail.text)
        setLog((current) => `${current}${tail.text}`.slice(-120000));
      if (disconnected.current)
        notify(
          "Live updates restored",
          "The run workspace is connected again.",
        );
      disconnected.current = false;
    } catch (failure) {
      if (!hasRun.current) setError(failure.message);
      if (!disconnected.current)
        notify("Live updates paused", failure.message, "bad");
      disconnected.current = true;
    } finally {
      loading.current = false;
    }
  };
  useWebSocketUpdates({ jobId, onChange: load, notify, enabled: autoUpdate, onStatus: setConnStatus });
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    offset.current = 0;
    setLog("");
    load();
  }, [jobId]);
  useEffect(() => {
    if (!autoUpdate) return;
    const timer = setInterval(() => loadRef.current(), 3000);
    return () => clearInterval(timer);
  }, [jobId, autoUpdate]);
  const toggleAutoUpdate = () => {
    setAutoUpdate((current) => {
      const next = !current;
      try {
        localStorage.setItem(AUTO_UPDATE_KEY, next ? "1" : "0");
      } catch {}
      if (next) setTimeout(() => loadRef.current(), 50);
      return next;
    });
  };
  async function control(path, title) {
    try {
      const body = new URLSearchParams({ job_id: jobId });
      await request(path, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      notify(title, "Pipeline state changed.");
      setTimeout(load, 400);
    } catch (failure) {
      notify(`${title} failed`, failure.message, "bad");
    }
  }
  async function stopRelease() {
    if (!confirm("Stop this Release? Its partial package stays available for inspection, and no automatic Telegram resend will occur.")) return;
    try {
      await request("/api/releases/stop", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ job_id: jobId }),
      });
      notify("Release stopped", "The partial release revision was preserved. Start Release again to create a new revision.");
      setTimeout(load, 400);
    } catch (failure) {
      notify("Release stop failed", failure.message, "bad");
    }
  }
  async function resolveFallback(action) {
    try {
      const body = new URLSearchParams({ job_id: jobId, fallback_action: action });
      await request("/api/fallback-action", { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
      notify(action === "approve" ? "Gemini fallback approved" : "Retrying ChatGPT", "The pipeline resumed from the waiting stage.");
      setTimeout(load, 400);
    } catch (failure) {
      notify("Fallback action failed", failure.message, "bad");
    }
  }
  async function archiveRun() {
    if (
      !confirm(
        "Archive this run from Studio history? Generated project files will be kept.",
      )
    )
      return;
    try {
      const body = new URLSearchParams({ job_id: jobId });
      await request("/delete", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
      });
      notify("Run archived", "All generated project files were kept.");
      goHome();
    } catch (failure) {
      notify("Archive failed", failure.message, "bad");
    }
  }
  if (error)
    return (
      <main className="center">
        <h1>Run unavailable</h1>
        <p>{error}</p>
        <button className="secondary" onClick={goHome}>
          Back to runs
        </button>
      </main>
    );
  if (!run)
    return (
      <main className="center">
        <div className="spinner" />
        Loading run…
      </main>
    );
  const done = run.graph.nodes.filter((node) =>
    ["DONE", "REUSED"].includes(node.status),
  ).length;
  const dependents = dependentNodeIds(run.graph.edges, selected?.id);
  const release = run.job.release || {};
  const releaseRunning = release.status === "RUNNING";
  const releaseDone = release.status === "DONE";
  const releaseRetryable = ["FAILED", "STOPPED", "NEEDS_REVIEW"].includes(release.status);
  return (
    <main className="run-page">
      <header className="run-header">
        <button className="back" onClick={goHome}>
          ← Runs
        </button>
        <div className="run-title">
          <span className="eyebrow">RUN {run.job.video_id}</span>
          <h1>{run.job.topic}</h1>
          <small>
            {done}/{run.graph.nodes.length} stages ready
          </small>
        </div>
        <div className="run-actions">
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <button
            className="secondary"
            disabled={run.job.live || run.job.read_only}
            title={
              run.job.read_only
                ? "This run was started outside Studio and has no editable frozen input record."
                : undefined
            }
            onClick={() => setConfigOpen(true)}
          >
            Revise inputs
          </button>
          {run.job.stoppable && (
            <button
              className="secondary danger"
              onClick={() => control("/stop", "Pipeline stopped")}
            >
              Stop
            </button>
          )}
          {run.job.resumable && (
            <button
              className="secondary"
              onClick={() => control("/resume", "Pipeline resumed")}
            >
              Resume
            </button>
          )}
          {(run.job.release_available || releaseRunning || releaseDone || releaseRetryable) && (
            <>
            {releaseRunning && <button className="secondary danger" onClick={stopRelease}>Stop Release</button>}
            <button
              className="primary"
              disabled={!run.job.release_available || releaseRunning}
              title={
                releaseRunning
                  ? "Release is generating metadata, thumbnail, and Telegram delivery."
                  : run.job.release_available
                    ? "Create the complete YouTube Shorts release package and send it to Telegram."
                    : run.job.release_reason || undefined
              }
              onClick={() => setReleaseOpen(true)}
            >
              {releaseRunning
                ? "Release in progress…"
                : releaseDone
                  ? "Release delivered"
                  : releaseRetryable
                    ? "Rerun Release →"
                    : "Release →"}
            </button>
            </>
          )}
          {!run.job.live && !run.job.read_only && (
            <button className="secondary danger" onClick={archiveRun}>
              Archive
            </button>
          )}
          {run.job.read_only && (
            <span className="state waiting">read only</span>
          )}
          <ConnectionStatus
            status={connStatus}
            autoUpdate={autoUpdate}
            onToggle={toggleAutoUpdate}
            onRefresh={load}
          />
          <StatusPill status={run.job.status} />
        </div>
      </header>
      <nav className="workspace-nav">
        <div className="segmented">
          <button
            className={view === "board" ? "active" : ""}
            onClick={() => setView("board")}
          >
            Pipeline board
          </button>
          <button
            className={view === "graph" ? "active" : ""}
            onClick={() => setView("graph")}
          >
            Dependency graph
          </button>
        </div>
        <div className="legend">
          <span className="done">● done</span>
          <span className="reused">● reused</span>
          <span className="running">● running</span>
          <span className="failed">● attention</span>
          {selected && <>
            <span className="selection-key selected-key">● selected</span>
            <span className="selection-key">● affected downstream</span>
          </>}
        </div>
      </nav>
      <div className="workspace">
        {view === "board" ? (
          <PipelineBoard
            graph={run.graph}
            selected={selected}
            dependents={dependents}
            choose={setSelected}
          />
        ) : (
          <DependencyGraph run={run} selected={selected} choose={setSelected} theme={theme} />
        )}
        <NodeDetail
          run={run}
          node={selected}
          close={() => setSelected(null)}
          regenerate={setRevisionNode}
          fallbackAction={run.fallback_action}
          resolveFallback={resolveFallback}
        />
      </div>
      <ActivityPanel
        events={run.activity || []}
        log={log}
        open={drawer}
        toggle={() => setDrawer((value) => !value)}
      />
      {revisionNode && (
        <RegenerationModal
          run={run}
          node={revisionNode}
          close={() => setRevisionNode(null)}
          started={(response) => {
            setRevisionNode(null);
            notify(
              "Regeneration started",
              `${response.revision.affected_nodes.length} stages affected; ${response.revision.reused_nodes.length} reused.`,
            );
            load();
          }}
        />
      )}
      {configOpen && (
        <ConfigModal
          run={run}
          close={() => setConfigOpen(false)}
          done={(response) => {
            setConfigOpen(false);
            if (response?.new_run && response?.job_id) {
              notify(
                "New pipeline run launched",
                "The topic changed, so the previous run and its artifacts were kept separate.",
              );
              goRun(response.job_id);
            } else {
              notify(
                "Configuration revision started",
                "Only the affected graph branch will rebuild.",
              );
              load();
            }
          }}
        />
      )}
      {releaseOpen && (
        <ReleaseModal
          jobId={jobId}
          close={() => setReleaseOpen(false)}
          started={() => {
            setReleaseOpen(false);
            notify("Release started", "The selected post-render operations are running.");
            setTimeout(load, 400);
          }}
        />
      )}
    </main>
  );
}

class StudioErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    console.error("Studio render failure", error, info);
    try {
      sessionStorage.setItem("studio.lastRenderError", JSON.stringify({
        at: new Date().toISOString(), message: String(error?.message || error),
        componentStack: String(info?.componentStack || "").slice(0, 4000),
      }));
    } catch {}
  }
  render() {
    if (!this.state.error) return this.props.children;
    return <main className="studio-recovery" role="alert">
      <span className="eyebrow">RECOVERY MODE</span>
      <h1>The Studio hit a display error</h1>
      <p>Your run and generated files are safe. Reload the interface; if the problem repeats, reset the two local display preferences.</p>
      <code>{String(this.state.error?.message || "Unknown interface error")}</code>
      <div>
        <button className="primary" type="button" onClick={() => location.reload()}>Reload Studio</button>
        <button type="button" onClick={() => {
          try { localStorage.removeItem(THEME_KEY); localStorage.removeItem(AUTO_UPDATE_KEY); } catch {}
          location.assign("/");
        }}>Reset display &amp; go home</button>
      </div>
    </main>;
  }
}

function App() {
  const [path, setPath] = useState(location.pathname),
    [toasts, setToasts] = useState([]),
    [theme, toggleTheme] = useTheme();
  const notify = (title, body, kind = "") => {
    const id = crypto.randomUUID();
    setToasts((items) => [...items, { id, title, body, kind }].slice(-5));
    setTimeout(
      () => setToasts((items) => items.filter((item) => item.id !== id)),
      7000,
    );
  };
  const navigate = (next) => {
    history.pushState({}, "", next);
    setPath(next);
    window.scrollTo(0, 0);
  };
  useEffect(() => {
    const pop = () => setPath(location.pathname);
    addEventListener("popstate", pop);
    return () => removeEventListener("popstate", pop);
  }, []);
  const match = path.match(/^\/runs\/([a-f0-9-]{36})$/);
  const page = path === "/new" ? "new" : path === "/runs" ? "runs" : "home";
  return (
    <>
      <Toasts
        items={toasts}
        dismiss={(id) =>
          setToasts((items) => items.filter((item) => item.id !== id))
        }
      />
      {match ? (
        <RunPage
          key={match[1]}
          jobId={match[1]}
          goHome={() => navigate("/")}
          goRun={(id) => navigate(`/runs/${id}`)}
          notify={notify}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      ) : (
        <Home open={(id) => navigate(`/runs/${id}`)} go={navigate} page={page} notify={notify} theme={theme} onToggleTheme={toggleTheme} />
      )}
    </>
  );
}

const studioRoot = document.getElementById("root");
if (studioRoot) createRoot(studioRoot).render(<StudioErrorBoundary><App /></StudioErrorBoundary>);
