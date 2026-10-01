import { useEffect, useMemo, useState } from "react";
import { ArrowCounterClockwise, Check, CircleNotch, ImageSquare, Plus, Stack, WarningCircle } from "@phosphor-icons/react";
import "./ThumbnailStylesWorkspace.css";
import { Channel, ThumbnailPreset, ThumbnailStyle, workerRequest } from "./worker";

type Props = {
  channels: Channel[];
  selectedChannelId: string | null;
  onRefresh: () => void;
};

const DEFAULT_STYLE: ThumbnailStyle = {
  background_type: "gradient",
  background_color: "#183F35",
  gradient_end_color: "#A9B96B",
  gradient_angle: 35,
  font_family: "Arial",
  font_size: 84,
  text_color: "#FFFFFF",
  outline_color: "#11221B",
  outline_width: 3,
  shadow: 4,
  alignment: "center",
  position_x: 50,
  position_y: 54,
  max_width_percent: 84,
  fit_mode: "shrink",
};

function previewBackground(style: ThumbnailStyle) {
  if (style.background_type === "solid") return style.background_color;
  return "linear-gradient(" + style.gradient_angle + "deg, " + style.background_color + ", " + style.gradient_end_color + ")";
}

export default function ThumbnailStylesWorkspace({ channels, selectedChannelId, onRefresh }: Props) {
  const [presets, setPresets] = useState<ThumbnailPreset[]>([]);
  const [selectedPresetId, setSelectedPresetId] = useState("");
  const [name, setName] = useState("New thumbnail style");
  const [style, setStyle] = useState<ThumbnailStyle>(DEFAULT_STYLE);
  const [targets, setTargets] = useState<string[]>(selectedChannelId ? [selectedChannelId] : []);
  const [defaultChannelId, setDefaultChannelId] = useState(selectedChannelId ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedPreset = useMemo(() => presets.find((preset) => preset.id === selectedPresetId) ?? null, [presets, selectedPresetId]);

  async function refreshPresets(preferredId?: string) {
    const next = await workerRequest<ThumbnailPreset[]>("thumbnail.presets.list", { all: true });
    setPresets(next);
    const nextId = preferredId ?? selectedPresetId;
    const match = next.find((preset) => preset.id === nextId) ?? next.find((preset) => preset.owner_channel_id === selectedChannelId) ?? next[0] ?? null;
    setSelectedPresetId(match?.id ?? "");
    if (match) {
      setName(match.name);
      setStyle(match.style);
      setTargets(await workerRequest<string[]>("thumbnail.presets.channels", { preset_id: match.id }));
    }
  }

  useEffect(() => {
    void refreshPresets().catch((caught) => setError(String(caught)));
    // The preset library is loaded once when this workspace opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function selectPreset(presetId: string) {
    setSelectedPresetId(presetId);
    const preset = presets.find((item) => item.id === presetId);
    if (preset) {
      setName(preset.name);
      setStyle(preset.style);
      setTargets(await workerRequest<string[]>("thumbnail.presets.channels", { preset_id: preset.id }));
    }
  }

  function newPreset() {
    setSelectedPresetId("");
    setName("New thumbnail style");
    setStyle(DEFAULT_STYLE);
    setTargets(selectedChannelId ? [selectedChannelId] : []);
    setError(null);
    setNotice(null);
  }

  function patchStyle<K extends keyof ThumbnailStyle>(key: K, value: ThumbnailStyle[K]) {
    setStyle((current) => ({ ...current, [key]: value }));
  }

  function toggleTarget(channelId: string) {
    setTargets((current) => current.includes(channelId)
      ? current.filter((id) => id !== channelId)
      : [...current, channelId]);
  }

  async function savePreset() {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const saved = selectedPresetId
        ? await workerRequest<ThumbnailPreset>("thumbnail.presets.update", { preset_id: selectedPresetId, name, style })
        : await workerRequest<ThumbnailPreset>("thumbnail.presets.create", { name, style });
      if (targets.length) {
        await workerRequest("thumbnail.presets.assign_channels", { preset_id: saved.id, channel_ids: targets });
      }
      if (defaultChannelId && targets.includes(defaultChannelId)) {
        await workerRequest("channels.set_default_thumbnail_preset", { channel_id: defaultChannelId, preset_id: saved.id });
      }
      await refreshPresets(saved.id);
      onRefresh();
      setNotice("Thumbnail style saved. The selected channels will rotate it with their other presets.");
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  const fontScale = Math.max(15, Math.min(43, style.font_size * 0.42));
  const previewText = <span style={{
    position: "absolute",
    left: style.position_x + "%",
    top: style.position_y + "%",
    width: style.max_width_percent + "%",
    transform: "translate(-50%, -50%)",
    color: style.text_color,
    fontFamily: style.font_family + ", sans-serif",
    fontSize: fontScale + "px",
    textAlign: style.alignment,
    lineHeight: 1.02,
    fontWeight: 800,
    WebkitTextStroke: Math.max(0.3, style.outline_width * 0.35) + "px " + style.outline_color,
    textShadow: style.shadow ? "0 " + Math.max(1, style.shadow * 0.35) + "px " + Math.max(2, style.shadow) + "px #0009" : "none",
    overflowWrap: "anywhere",
  }}>SOURCE THUMBNAIL<br />TEXT PREVIEW</span>;

  return (
    <section className="thumbnail-style-workspace">
      <div className="thumbnail-style-heading">
        <div><span className="eyebrow">THUMBNAIL DESIGN</span><h1>Thumbnail styles</h1><p>Build complete background + typography presets, preview them here, then rotate them per channel or batch.</p></div>
        <button className="button button-primary" type="button" onClick={newPreset}><Plus size={16} /> New style</button>
      </div>
      {error && <div className="thumbnail-style-alert error"><WarningCircle size={16} /><span>{error}</span></div>}
      {notice && <div className="thumbnail-style-alert success"><Check size={16} /><span>{notice}</span></div>}
      <div className="thumbnail-style-layout">
        <aside className="thumbnail-style-library">
          <div className="thumbnail-library-heading"><div><Stack size={16} /><strong>Preset library</strong></div><span>{presets.length} styles</span></div>
          <div className="thumbnail-preset-list">
            {presets.map((preset) => <button type="button" key={preset.id} className={preset.id === selectedPresetId ? "selected" : ""} onClick={() => selectPreset(preset.id)}>
              <span className="thumbnail-preset-swatch" style={{ background: previewBackground(preset.style) }} />
              <span><strong>{preset.name}</strong><small>{preset.owner_channel_id ? channels.find((channel) => channel.id === preset.owner_channel_id)?.name ?? "Channel style" : "Shared style"}</small></span>
            </button>)}
            {!presets.length && <div className="thumbnail-library-empty">Create a style to start a rotation pool.</div>}
          </div>
        </aside>

        <div className="thumbnail-editor">
          <section className="thumbnail-preview-card">
            <div className="thumbnail-preview-header"><div><span className="eyebrow">LIVE PREVIEW</span><strong>{selectedPreset ? "Style preview" : "New style preview"}</strong></div><span>1280 × 720</span></div>
            <div className="thumbnail-preview-stage" style={{ background: previewBackground(style) }}>
              <div className="thumbnail-preview-grid" />
              {previewText}
              <small className="thumbnail-preview-badge">PRESET</small>
            </div>
            <div className="thumbnail-preview-foot"><ImageSquare size={14} /><span>Uses sample text for layout. Each video starts with OCR from its downloaded source thumbnail.</span></div>
          </section>

          <section className="thumbnail-editor-card">
            <div className="thumbnail-editor-title"><div><span className="eyebrow">PRESET CONFIGURATION</span><h2>{selectedPreset ? "Edit style" : "Create style"}</h2></div><span className="style-scope-tag">{selectedPreset?.owner_channel_id ? "Channel preset" : selectedPreset ? "Shared preset" : "New preset"}</span></div>
            <div className="thumbnail-field-grid">
              <label className="wide"><span>Preset name</span><input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} /></label>
              <label><span>Background</span><select value={style.background_type} onChange={(event) => patchStyle("background_type", event.target.value as ThumbnailStyle["background_type"])}><option value="gradient">Gradient</option><option value="solid">Solid</option></select></label>
              <label><span>Gradient angle</span><input type="number" min={0} max={360} value={style.gradient_angle} onChange={(event) => patchStyle("gradient_angle", Number(event.target.value))} disabled={style.background_type === "solid"} /></label>
              <label><span>Start color</span><input type="color" value={style.background_color} onChange={(event) => patchStyle("background_color", event.target.value)} /></label>
              {style.background_type === "gradient" && <label><span>End color</span><input type="color" value={style.gradient_end_color} onChange={(event) => patchStyle("gradient_end_color", event.target.value)} /></label>}
              <label className="wide"><span>Font family</span><input value={style.font_family} onChange={(event) => patchStyle("font_family", event.target.value)} placeholder="Arial, Georgia, ..." /></label>
              <label><span>Font size · px</span><input type="number" min={24} max={200} value={style.font_size} onChange={(event) => patchStyle("font_size", Number(event.target.value))} /></label>
              <label><span>Text color</span><input type="color" value={style.text_color} onChange={(event) => patchStyle("text_color", event.target.value)} /></label>
              <label><span>Outline color</span><input type="color" value={style.outline_color} onChange={(event) => patchStyle("outline_color", event.target.value)} /></label>
              <label><span>Outline · px</span><input type="number" min={0} max={16} step={0.5} value={style.outline_width} onChange={(event) => patchStyle("outline_width", Number(event.target.value))} /></label>
              <label><span>Shadow · px</span><input type="number" min={0} max={32} value={style.shadow} onChange={(event) => patchStyle("shadow", Number(event.target.value))} /></label>
              <label><span>Text alignment</span><select value={style.alignment} onChange={(event) => patchStyle("alignment", event.target.value as ThumbnailStyle["alignment"])}><option value="left">Left</option><option value="center">Center</option><option value="right">Right</option></select></label>
              <label><span>Fit rule</span><select value={style.fit_mode} onChange={(event) => patchStyle("fit_mode", event.target.value as ThumbnailStyle["fit_mode"])}><option value="shrink">Shrink to fit</option><option value="wrap">Wrap text</option></select></label>
              <label className="range-field"><span>Horizontal position · {style.position_x}%</span><input type="range" min={0} max={100} value={style.position_x} onChange={(event) => patchStyle("position_x", Number(event.target.value))} /></label>
              <label className="range-field"><span>Vertical position · {style.position_y}%</span><input type="range" min={0} max={100} value={style.position_y} onChange={(event) => patchStyle("position_y", Number(event.target.value))} /></label>
              <label className="range-field wide"><span>Maximum text width · {style.max_width_percent}%</span><input type="range" min={30} max={95} value={style.max_width_percent} onChange={(event) => patchStyle("max_width_percent", Number(event.target.value))} /></label>
            </div>
          </section>

          <section className="thumbnail-sharing-card">
            <div><span className="eyebrow">ROTATION POOLS</span><h2>Share this style</h2><p>Selected Channels add this complete preset to their balanced rotation pool.</p></div>
            <div className="channel-target-list">{channels.map((channel) => <label key={channel.id}><input type="checkbox" checked={targets.includes(channel.id)} onChange={() => toggleTarget(channel.id)} /><span>{channel.name}</span><small>{channel.thumbnail_preset_count} styles</small></label>)}</div>
            <label className="default-style-select"><span>Set as default for a selected Channel</span><select value={defaultChannelId} onChange={(event) => setDefaultChannelId(event.target.value)}><option value="">Keep current defaults</option>{channels.filter((channel) => targets.includes(channel.id)).map((channel) => <option value={channel.id} key={channel.id}>{channel.name}</option>)}</select></label>
            <div className="thumbnail-editor-actions"><span>{targets.length ? "Will be added to " + targets.length + " Channel pool" + (targets.length === 1 ? "" : "s") : "Saved in the shared library only"}</span><button className="button button-secondary" type="button" onClick={() => { setStyle(DEFAULT_STYLE); setName(selectedPreset?.name ?? "New thumbnail style"); }}><ArrowCounterClockwise size={15} /> Reset preview</button><button className="button button-primary" type="button" onClick={() => void savePreset()} disabled={busy || !name.trim()}>{busy ? <CircleNotch className="spin" size={15} /> : <Check size={15} />} Save style</button></div>
          </section>
        </div>
      </div>
    </section>
  );
}
