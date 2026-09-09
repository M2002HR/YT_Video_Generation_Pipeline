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
