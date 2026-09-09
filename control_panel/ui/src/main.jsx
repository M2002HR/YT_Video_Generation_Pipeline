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
  statusClass,
  validateLaunchValues,
} from "./studio-utils.js";

const PHASE_LABELS = {
  creative: "Creative",
  visual: "Visuals",
  opening: "Opening",
  audio: "Audio",
  edit: "Edit & motion",
  render: "Render & QC",
  publish: "Publishing",
};
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

function useWebSocketUpdates({ jobId, onChange, notify }) {
  const change = useRef(onChange);
  const announce = useRef(notify);
  useEffect(() => {
    change.current = onChange;
    announce.current = notify;
  });
  useEffect(() => {
    let socket, retry, closed = false, opened = false;
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const endpoint = `${protocol}//${location.host}/api/ws${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ""}`;
    const connect = () => {
      if (closed) return;
      socket = new WebSocket(endpoint);
      socket.onopen = () => {
        if (opened) announce.current("Live updates restored", "Updates are arriving without refresh.");
        opened = true;
      };
      socket.onmessage = (event) => {
        try {
          if (JSON.parse(event.data).type === "changed") change.current();
        } catch {
          // Ignore malformed notifications; the next valid server event will reconcile state.
        }
      };
      socket.onclose = () => {
        if (closed) return;
        announce.current("Live updates reconnecting", "The workspace will reconnect automatically.", "warn");
        retry = setTimeout(connect, 3000);
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, [jobId]);
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

function Field({ field, value, onChange }) {
  const id = `field-${field.name}`;
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
    onChange: (e) => onChange(field.name, e.target.value),
  };
  if (field.type === "toggle")
    return (
      <label
        className={`toggle-field ${field.advanced ? "advanced-field" : ""}`}
        htmlFor={id}
      >
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
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
      className={`field ${field.width === "half" ? "half" : ""} ${field.advanced ? "advanced-field" : ""}`}
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
            <option key={option.value} value={option.value}>
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
  const select = (styleId, nextPolicy) => {
    change("world_style_id", styleId);
    change("world_style_policy", nextPolicy);
  };
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
          <b>＋ Create a new style</b><span>Describe the desired look below; a new reusable anchor is created.</span>
        </button>
      </div>
      <div className="style-card-grid" aria-live="polite">
        {styles.map((style) => {
          const active = selectedId === style.style_id && policy === "reuse";
          return (
            <button
              type="button"
              key={style.style_id}
              className={`style-card ${active ? "selected" : ""}`}
              aria-pressed={active}
              onClick={() => select(style.style_id, "reuse")}
            >
              <div className="style-images">
                {style.anchor_available ? <img loading="lazy" src={style.anchor_url} alt={`${style.display_name} style anchor`} /> : <span className="style-image-empty">Preview unavailable</span>}
                {style.sample_available && <div className="style-sample"><img loading="lazy" src={style.sample_url} alt={`${style.display_name} generated beat`} /><span>Generated beat</span></div>}
              </div>
              <div className="style-card-copy">
                <b>{style.display_name}</b>
                <span>{style.medium_family || "Visual style"}{style.texture_family ? ` · ${style.texture_family}` : ""}</span>
                {style.palette_summary && <small>{style.palette_summary}</small>}
              </div>
              {active && <i className="style-selected-mark">✓ Selected</i>}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SettingsGroup({ group, values, change, open, toggle, styles, stylesLoading }) {
  const [advanced, setAdvanced] = useState(false);
  const advancedCount = group.fields.filter((field) => field.advanced).length;
  return (
    <section className={`settings-group ${open ? "open" : ""}`}>
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
      {open && (
        <div className="field-grid">
          {group.id === "visual" && <StyleLibrary styles={styles} loading={stylesLoading} values={values} change={change} />}
          {group.fields
            .filter((field) => group.id !== "visual" || !["world_style_id", "world_style_policy"].includes(field.name))
            .filter((field) => advanced || !field.advanced)
            .map((field) => (
              <Field
                key={field.name}
                field={field}
                value={values[field.name]}
                onChange={change}
              />
            ))}
          {advancedCount > 0 && (
            <button
              type="button"
              className="advanced-toggle"
              onClick={() => setAdvanced((value) => !value)}
            >
              {advanced
                ? "Hide advanced motion settings"
                : `Show ${advancedCount} advanced motion settings`}
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
  const [openGroups, setOpenGroups] = useState(
    () => new Set(schema.groups.filter((group) => !group.collapsed).map((group) => group.id)),
  );
  useEffect(() => setValues(initial || {}), [initial]);
  useEffect(() => {
    const project = values.content_project;
    if (project !== "question_harvest") {
      setStyles([]);
      return;
    }
    let cancelled = false;
    setStylesLoading(true);
    request(`/api/style-catalog?content_project=${encodeURIComponent(project)}`)
      .then((data) => !cancelled && setStyles(data.styles || []))
      .catch((failure) => !cancelled && notify("Style previews unavailable", failure.message, "warn"))
      .finally(() => !cancelled && setStylesLoading(false));
    return () => { cancelled = true; };
  }, [values.content_project]);
  const change = (name, value) =>
    setValues((current) => ({ ...current, [name]: value }));
  const applicableGroups = schema.groups.filter(
    (group) =>
      !group.projects || group.projects.includes(values.content_project),
  );
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
          styles={styles}
          stylesLoading={stylesLoading}
          open={openGroups.has(group.id)}
          toggle={() =>
            setOpenGroups((current) => {
              const next = new Set(current);
              if (next.has(group.id)) next.delete(group.id);
              else next.add(group.id);
              return next;
            })
          }
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

function Home({ open, notify }) {
  const [jobs, setJobs] = useState([]),
    [health, setHealth] = useState(null),
    [contract, setContract] = useState(null),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState("all"),
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
  useWebSocketUpdates({ onChange: load, notify });
  useEffect(() => {
    load();
    loadContract();
  }, []);
  const shown = jobs.filter(
    (job) =>
      (status === "all" || statusClass(job.status) === status) &&
      `${job.video_id} ${job.topic}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const active = jobs.find((job) => job.live);
  return (
    <main className="home">
      <header className="brand">
        <div>
          <span className="eyebrow">VIDEO GENERATION PIPELINE</span>
          <h1>Studio</h1>
        </div>
        <ProviderHealth health={health} />
      </header>
      <section className="dashboard-hero">
        <div>
          <span className="eyebrow">PRODUCTION CONTROL</span>
          <h2>
            One place to create,
            <br />
            inspect and improve.
          </h2>
          <p>
            Every stage is observable. Every artifact is versioned. Every
            regeneration follows the dependency graph.
          </p>
        </div>
        <div
          className={`active-card ${active ? "live" : ""} ${health && !health.reachable ? "bad" : ""}`}
        >
          <span>
            {active
              ? "ACTIVE RUN"
              : health && !health.reachable
                ? "PROVIDER ATTENTION"
                : "SYSTEM READY"}
          </span>
          <b>
            {active
              ? `${active.video_id} · ${active.topic}`
              : health && !health.reachable
                ? "Ordak is currently unavailable"
                : "No pipeline is using the providers"}
          </b>
          <small>
            {active?.pipeline?.running
              ? label(active.pipeline.running)
              : health && !health.reachable
                ? "Restore provider access before launching"
                : "Ready for a new run"}
          </small>
        </div>
      </section>
      {contract ? (
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
      )}
      <section className="runs">
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
      </section>
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
        return (
          <section key={phase} className="phase-column">
            <header>
              <span>{PHASE_LABELS[phase]}</span>
              <b>
                {nodes.filter((node) => READY.has(node.status)).length}/
                {nodes.length}
              </b>
            </header>
            {nodes.map((node) => (
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
          </section>
        );
      })}
    </div>
  );
}

function DependencyGraph({ run, selected, choose }) {
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
          stroke: selected?.id === edge.source && dependents.has(edge.target) ? "#b58cff" : "#53647d",
          strokeWidth: selected?.id === edge.source ? 2 : 1.2,
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
        <Background gap={24} color="#273246" />
        <Controls />
        <MiniMap
          pannable
          zoomable
          nodeColor={(node) =>
            node.data?.status === "RUNNING"
              ? "#f2bb61"
              : node.data?.status === "DONE"
                ? "#38d996"
                : "#53647d"
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
        disabled={run.job.live || run.job.read_only}
        onClick={() => regenerate(node)}
      >
        {run.job.read_only
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
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    request("/api/regenerations/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: run.job.job_id, node_ids: [node.id] }),
    })
      .then(setPlan)
      .catch((failure) => setError(failure.message));
  }, [run.job.job_id, node.id]);
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
        <p>
          The selected stage and every data-dependent descendant will be
          versioned and rebuilt. Everything else stays reusable.
        </p>
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
            Revision note <i>optional</i>
          </span>
          <textarea
            value={feedback}
            onChange={(event) => setFeedback(event.target.value)}
            maxLength={4000}
            placeholder="Describe what should change. For image beats this is added to the provider prompt."
          />
        </label>
        {error && (
          <div className="inline-error" role="alert">
            {error}
          </div>
        )}
        <button className="primary" disabled={busy || !plan || !plan.can_start}>
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

function ConfigModal({ run, close, done }) {
  const [schema, setSchema] = useState(null),
    [values, setValues] = useState(null),
    [plan, setPlan] = useState(null),
    [styles, setStyles] = useState([]),
    [stylesLoading, setStylesLoading] = useState(false),
    [openGroups, setOpenGroups] = useState(new Set(["visual"])),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    Promise.all([
      request(`/api/run/${run.job.job_id}/config`),
      request("/api/launch-schema"),
    ])
      .then(([data, contract]) => {
        setValues(data.values);
        setSchema(contract.schema);
      })
      .catch((failure) => setError(failure.message));
  }, [run.job.job_id]);
  useEffect(() => {
    if (!values?.content_project) return;
    let cancelled = false;
    setStylesLoading(true);
    request(`/api/style-catalog?content_project=${encodeURIComponent(values.content_project)}`)
      .then((data) => !cancelled && setStyles(data.styles || []))
      .catch((failure) => !cancelled && setError(failure.message))
      .finally(() => !cancelled && setStylesLoading(false));
    return () => { cancelled = true; };
  }, [values?.content_project]);
  useEffect(() => {
    if (!values) return;
    let cancelled = false;
    setPlan(null);
    const timer = setTimeout(() => {
      request("/api/config-revisions/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: run.job.job_id, values }),
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
  }, [run.job.job_id, values]);
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
      validateLaunchValues(values);
      await request("/api/config-revisions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: run.job.job_id,
          config: { values },
        }),
      });
      done();
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
      onMouseDown={(event) => event.target === event.currentTarget && close()}
    >
      <form className="modal config-modal" onSubmit={submit}>
        <button
          type="button"
          className="icon close"
          onClick={close}
          aria-label="Close"
        >
          ×
        </button>
        <span className="eyebrow">VERSIONED RUN SETTINGS</span>
        <h2 id="config-title">Revise this run safely</h2>
        <p>
          Edit the same controls used at launch. The impact preview identifies exactly
          which stages rebuild before any files are changed.
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
                  styles={styles}
                  stylesLoading={stylesLoading}
                  open={openGroups.has(group.id)}
                  toggle={() => setOpenGroups((current) => {
                    const next = new Set(current);
                    next.has(group.id) ? next.delete(group.id) : next.add(group.id);
                    return next;
                  })}
                />
              ))}
          </div>
        ) : !error && <div className="loading-line">Loading frozen settings…</div>}
        {plan && (
          <div className="config-review">
            <div className="change-summary">
              <span>{plan.changed_fields.length} changed setting(s)</span>
              {plan.changed_fields.map((name) => <b key={name}>{label(name)}</b>)}
            </div>
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

function RunPage({ jobId, goHome, notify }) {
  const [run, setRun] = useState(null),
    [selected, setSelected] = useState(null),
    [view, setView] = useState("board"),
    [revisionNode, setRevisionNode] = useState(null),
    [configOpen, setConfigOpen] = useState(false),
    [drawer, setDrawer] = useState(true),
    [log, setLog] = useState(""),
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
      const data = await request(`/api/run/${jobId}/graph`);
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
  useWebSocketUpdates({ jobId, onChange: load, notify });
  useEffect(() => {
    load();
  }, [jobId]);
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
          {!run.job.live && !run.job.read_only && (
            <button className="secondary danger" onClick={archiveRun}>
              Archive
            </button>
          )}
          {run.job.read_only && (
            <span className="state waiting">read only</span>
          )}
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
          <DependencyGraph run={run} selected={selected} choose={setSelected} />
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
          done={() => {
            setConfigOpen(false);
            notify(
              "Configuration revision started",
              "Only the affected graph branch will rebuild.",
            );
            load();
          }}
        />
      )}
    </main>
  );
}

function App() {
  const [path, setPath] = useState(location.pathname),
    [toasts, setToasts] = useState([]);
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
          notify={notify}
        />
      ) : (
        <Home open={(id) => navigate(`/runs/${id}`)} notify={notify} />
      )}
    </>
  );
}

createRoot(document.getElementById("root")).render(<App />);
