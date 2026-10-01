import { useEffect, useMemo, useState } from "react";
import { Check, CopySimple, FloppyDisk, Plus, Stack, WarningCircle } from "@phosphor-icons/react";
import { Channel, SubtitleFontInfo, SubtitlePreset, SubtitleStyle, workerRequest } from "./worker";
import "./SubtitleStylesWorkspace.css";

const DEFAULT_STYLE: SubtitleStyle = {
  font_family: "Arial", font_size: 40, text_color: "#FFFFFF", background_enabled: true,
  background_color: "#000000", background_opacity: 0.58, outline_color: "#000000",
  outline_width: 2, shadow: 1, alignment: "bottom-center", position_x: 50, position_y: 88,
};

const ALIGNMENTS: SubtitleStyle["alignment"][] = [
  "top-left", "top-center", "top-right", "middle-left", "middle-center", "middle-right",
  "bottom-left", "bottom-center", "bottom-right",
];

function colorWithAlpha(color: string, opacity: number) {
  const value = color.replace("#", "");
  return `rgba(${parseInt(value.slice(0, 2), 16)}, ${parseInt(value.slice(2, 4), 16)}, ${parseInt(value.slice(4, 6), 16)}, ${opacity})`;
}

function Preview({ style, text, aspectRatio }: { style: SubtitleStyle; text: string; aspectRatio: string }) {
  const [vertical, horizontal] = style.alignment.split("-");
  const transformX = horizontal === "left" ? "0" : horizontal === "right" ? "-100%" : "-50%";
  const transformY = vertical === "top" ? "0" : vertical === "bottom" ? "-100%" : "-50%";
  return <div className="caption-preview-stage">
    <div className="caption-preview-scene" style={{ aspectRatio }}><div className="caption-preview-horizon" /><div className="caption-preview-light" />
      <span className="caption-preview-text" style={{
        left: `${style.position_x}%`, top: `${style.position_y}%`, transform: `translate(${transformX}, ${transformY})`,
        color: style.text_color, fontFamily: style.font_family, fontSize: `clamp(10px, ${style.font_size / 7.2}px, 30px)`,
        backgroundColor: style.background_enabled ? colorWithAlpha(style.background_color, style.background_opacity) : "transparent",
        WebkitTextStroke: `${Math.max(0.35, style.outline_width / 2.5)}px ${style.outline_color}`,
        textShadow: style.shadow ? `0 ${style.shadow}px ${style.shadow * 1.6}px #000a` : "none",
      }}>{text || "Your caption appears here"}</span>
    </div>
    <div className="caption-preview-caption"><span>PREVIEW · 16:9 OUTPUT FRAME</span><small>Demo text can be replaced in a future preview update.</small></div>
  </div>;
}

export default function SubtitleStylesWorkspace() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [channelId, setChannelId] = useState("");
  const [presets, setPresets] = useState<SubtitlePreset[]>([]);
  const [presetId, setPresetId] = useState("");
  const [scope, setScope] = useState<"channel" | "shared">("channel");
  const [name, setName] = useState("");
  const [style, setStyle] = useState<SubtitleStyle>(DEFAULT_STYLE);
  const [editingExisting, setEditingExisting] = useState(false);
  const [demoText, setDemoText] = useState("Your caption appears here");
  const [previewAspectRatio, setPreviewAspectRatio] = useState("16 / 9");
  const [fontInfo, setFontInfo] = useState<SubtitleFontInfo | null>(null);
  const [checkingFont, setCheckingFont] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const channel = channels.find((item) => item.id === channelId) ?? null;
  const selected = presets.find((item) => item.id === presetId) ?? null;

  async function loadChannels(preferredId?: string) {
    const next = await workerRequest<Channel[]>("channels.list");
    setChannels(next);
    const selectedChannel = next.find((item) => item.id === (preferredId ?? channelId)) ?? next[0] ?? null;
    setChannelId(selectedChannel?.id ?? "");
  }

  async function loadPresets(nextScope = scope, nextChannelId = channelId, preferredPresetId?: string) {
    const next = await workerRequest<SubtitlePreset[]>("subtitles.presets.list", {
      channel_id: nextScope === "channel" ? nextChannelId : null,
    });
    setPresets(next);
    const defaultId = channels.find((item) => item.id === nextChannelId)?.default_subtitle_preset_id;
    const nextPreset = next.find((item) => item.id === (preferredPresetId ?? (nextScope === "channel" ? defaultId : presetId))) ?? next[0] ?? null;
    setPresetId(nextPreset?.id ?? "");
    setName(nextPreset?.name ?? "");
    setStyle(nextPreset?.style ?? DEFAULT_STYLE);
    setEditingExisting(Boolean(nextPreset));
  }

  useEffect(() => { void loadChannels().catch((caught) => setError(String(caught))); }, []);
  useEffect(() => {
    if (!channelId && scope === "channel") return;
    void loadPresets(scope, channelId).catch((caught) => setError(String(caught)));
    // Loading is intentionally tied to channel/scope changes. Preset selection is handled below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelId, scope]);
  useEffect(() => {
    let cancelled = false;
    setCheckingFont(true);
    const timer = window.setTimeout(() => {
      void workerRequest<SubtitleFontInfo>("subtitles.font.inspect", { font_family: style.font_family })
        .then((result) => { if (!cancelled) setFontInfo(result); })
        .catch((caught) => { if (!cancelled) setFontInfo({ font_family: style.font_family, available: null, matched_family: null, font_path: null, warning: String(caught) }); })
        .finally(() => { if (!cancelled) setCheckingFont(false); });
    }, 300);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [style.font_family]);

  function choosePreset(nextId: string) {
    setPresetId(nextId);
    const next = presets.find((item) => item.id === nextId);
    setName(next?.name ?? "");
    setStyle(next?.style ?? DEFAULT_STYLE);
    setEditingExisting(Boolean(next));
    setMessage("");
  }

  function startNew() {
    setPresetId("");
    setName(scope === "shared" ? "Shared captions" : `${channel?.name ?? "Channel"} captions`);
    setStyle(selected?.style ?? DEFAULT_STYLE);
    setEditingExisting(false);
    setMessage("");
    setError("");
  }

  async function save() {
    if (!name.trim()) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const saved = editingExisting && selected
        ? await workerRequest<SubtitlePreset>("subtitles.presets.update", { preset_id: selected.id, name, style })
        : await workerRequest<SubtitlePreset>("subtitles.presets.create", { channel_id: scope === "channel" ? channelId : null, name, style });
      await loadPresets(scope, channelId, saved.id);
      setMessage(editingExisting ? "Đã lưu thay đổi preset." : "Đã tạo preset phụ đề.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function duplicate() {
    if (!selected) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const copy = await workerRequest<SubtitlePreset>("subtitles.presets.duplicate", { preset_id: selected.id, name: `${selected.name} copy` });
      await loadPresets(scope, channelId, copy.id);
      setMessage("Đã nhân bản preset.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function setDefault() {
    if (!channel || !selected) return;
    setBusy(true); setError(""); setMessage("");
    try {
      await workerRequest("channels.set_default_subtitle_preset", { channel_id: channel.id, preset_id: selected.id });
      await loadChannels(channel.id);
      setMessage(`Đã đặt “${selected.name}” làm preset mặc định cho ${channel.name}.`);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  const update = <K extends keyof SubtitleStyle>(key: K, value: SubtitleStyle[K]) => setStyle((current) => ({ ...current, [key]: value }));
  const channelDefaultLabel = useMemo(() => channel?.default_subtitle_preset?.name ?? "Built-in default", [channel]);

  return <section className="subtitle-styles-workspace">
    <div className="subtitle-styles-heading"><div><span className="eyebrow">CAPTION DESIGN</span><h1>Kiểu phụ đề</h1><p>Tạo preset có thể tái sử dụng và xem nhanh trên khung 16:9 trước khi render.</p></div><button className="button button-primary" type="button" onClick={startNew}><Plus size={16} /> Preset mới</button></div>
    {error && <div className="style-alert error"><WarningCircle size={16} /><span>{error}</span></div>}
    {message && <div className="style-alert"><Check size={16} /><span>{message}</span></div>}
    <div className="subtitle-style-layout">
      <section className="style-editor-card">
        <div className="style-editor-top"><div><span className="eyebrow">THƯ VIỆN PRESET</span><h2>Thông số hiển thị</h2></div><span className="style-local-badge"><Stack size={13} /> Lưu cục bộ</span></div>
        <div className="style-scope-row">
          <label>Phạm vi<select value={scope} onChange={(event) => setScope(event.target.value as "channel" | "shared")}><option value="channel">Preset của một kênh</option><option value="shared">Preset dùng chung</option></select></label>
          {scope === "channel" && <label>Kênh<select value={channelId} onChange={(event) => setChannelId(event.target.value)}><option value="">Chọn kênh…</option>{channels.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
        </div>
        <div className="style-preset-row"><label>Preset đang chỉnh<select value={presetId} onChange={(event) => choosePreset(event.target.value)}><option value="">Preset mới…</option>{presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}{preset.channel_id ? " · kênh" : " · dùng chung"}</option>)}</select></label><button type="button" className="button button-secondary" onClick={startNew}><Plus size={14} /> Mới</button></div>
        {scope === "channel" && channel && <div className="default-preset-note">Preset mặc định của <strong>{channel.name}</strong>: {channelDefaultLabel}{selected?.id === channel.default_subtitle_preset_id && <span> · đang chọn</span>}</div>}
        <label className="style-field">Tên preset<input value={name} onChange={(event) => setName(event.target.value)} maxLength={80} placeholder="Ví dụ: trắng viền đen" /></label>
        <div className="style-controls-grid">
          <label className="style-field">Font<input value={style.font_family} onChange={(event) => update("font_family", event.target.value)} placeholder="Arial" />{checkingFont ? <small className="font-check-note">Đang kiểm tra font…</small> : fontInfo?.warning ? <small className="font-check-note warning" title={fontInfo.font_path ?? undefined}>{fontInfo.warning}</small> : fontInfo?.available ? <small className="font-check-note">Đã tìm thấy {fontInfo.matched_family}</small> : null}</label>
          <label className="style-field">Cỡ chữ <output>{style.font_size}px</output><input type="range" min="12" max="120" value={style.font_size} onChange={(event) => update("font_size", Number(event.target.value))} /></label>
          <label className="style-field color-control">Màu chữ<input type="color" value={style.text_color} onChange={(event) => update("text_color", event.target.value)} /><code>{style.text_color}</code></label>
          <label className="style-field color-control">Màu nền<input type="color" value={style.background_color} onChange={(event) => update("background_color", event.target.value)} /><code>{style.background_color}</code></label>
          <label className="style-field">Độ mờ nền <output>{Math.round(style.background_opacity * 100)}%</output><input type="range" min="0" max="100" value={Math.round(style.background_opacity * 100)} onChange={(event) => update("background_opacity", Number(event.target.value) / 100)} /></label>
          <label className="style-check"><input type="checkbox" checked={style.background_enabled} onChange={(event) => update("background_enabled", event.target.checked)} /> Hiện nền sau chữ</label>
          <label className="style-field color-control">Màu viền<input type="color" value={style.outline_color} onChange={(event) => update("outline_color", event.target.value)} /><code>{style.outline_color}</code></label>
          <label className="style-field">Độ dày viền <output>{style.outline_width}px</output><input type="range" min="0" max="12" step="0.5" value={style.outline_width} onChange={(event) => update("outline_width", Number(event.target.value))} /></label>
          <label className="style-field">Bóng chữ <output>{style.shadow}px</output><input type="range" min="0" max="12" step="0.5" value={style.shadow} onChange={(event) => update("shadow", Number(event.target.value))} /></label>
          <label className="style-field">Căn chỉnh<select value={style.alignment} onChange={(event) => update("alignment", event.target.value as SubtitleStyle["alignment"])}>{ALIGNMENTS.map((alignment) => <option key={alignment} value={alignment}>{alignment.replace("-", " · ")}</option>)}</select></label>
          <label className="style-field">Vị trí ngang <output>{style.position_x}%</output><input type="range" min="0" max="100" value={style.position_x} onChange={(event) => update("position_x", Number(event.target.value))} /></label>
          <label className="style-field">Vị trí dọc <output>{style.position_y}%</output><input type="range" min="0" max="100" value={style.position_y} onChange={(event) => update("position_y", Number(event.target.value))} /></label>
        </div>
        <div className="style-editor-actions"><button type="button" className="button button-secondary" onClick={() => void duplicate()} disabled={!selected || busy}><CopySimple size={15} /> Nhân bản</button>{scope === "channel" && <button type="button" className="button button-secondary" onClick={() => void setDefault()} disabled={!channel || !selected || busy}><Check size={15} /> Đặt mặc định</button>}<button type="button" className="button button-primary" onClick={() => void save()} disabled={busy || !name.trim()}><FloppyDisk size={15} /> {busy ? "Đang lưu…" : editingExisting ? "Lưu thay đổi" : "Tạo preset"}</button></div>
      </section>
      <section className="style-preview-card"><div className="style-editor-top"><div><span className="eyebrow">XEM TRƯỚC</span><h2>Minh họa chữ phụ đề</h2></div><label className="preview-dimension-select"><span>Khung</span><select value={previewAspectRatio} onChange={(event) => setPreviewAspectRatio(event.target.value)}><option value="16 / 9">16:9</option><option value="9 / 16">9:16</option><option value="4 / 3">4:3</option><option value="1 / 1">1:1</option><option value="3 / 4">3:4</option></select></label></div><label className="style-field preview-demo-field">Chữ minh họa<input value={demoText} onChange={(event) => setDemoText(event.target.value)} maxLength={120} /></label><Preview style={style} text={demoText} aspectRatio={previewAspectRatio} /><div className="preview-footnote">Khung xem trước chỉ minh họa vị trí và kiểu chữ. Render cuối dùng font có trên máy.</div></section>
    </div>
  </section>;
}
