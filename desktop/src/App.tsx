import { useEffect, useMemo, useState } from "react";
import {
  Archive,
  ArrowDownRight,
  Check,
  CheckCircle,
  CircleNotch,
  CopySimple,
  FilmSlate,
  FolderOpen,
  GearSix,
  MagnifyingGlass,
  ImageSquare,
  PencilSimple,
  Plus,
  Stack,
  TextT,
  VideoCamera,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { open } from "@tauri-apps/plugin-dialog";
import "./App.css";
import { BackgroundAsset, Channel, DynamicToolchainState, LocalToolchainState, OcrLanguage, ThumbnailMode, ThumbnailPreset, workerRequest } from "./worker";
import BatchWorkspace from "./BatchWorkspace";
import SubtitleStylesWorkspace from "./SubtitleStylesWorkspace";
import ThumbnailStylesWorkspace from "./ThumbnailStylesWorkspace";
import SettingsWorkspace from "./SettingsWorkspace";
import StartupSplash, { StartupStage } from "./StartupSplash";

type DialogMode = "create" | "edit" | "duplicate" | "library" | null;

function formatDuration(seconds: number | null) {
  if (seconds === null || !Number.isFinite(seconds)) return "Duration unavailable";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const remainder = total % 60;
  return hours > 0
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`
    : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function formatFrameRate(rate: number | null) {
  return rate === null ? "— fps" : `${Number(rate.toFixed(2))} fps`;
}

function App() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [assets, setAssets] = useState<BackgroundAsset[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<DialogMode>(null);
  const [channelName, setChannelName] = useState("");
  const [subtitleLanguagesText, setSubtitleLanguagesText] = useState("");
  const [thumbnailLanguagesText, setThumbnailLanguagesText] = useState("");
  const [thumbnailPresets, setThumbnailPresets] = useState<ThumbnailPreset[]>([]);
  const [ocrLanguages, setOcrLanguages] = useState<OcrLanguage[]>([]);
  const [library, setLibrary] = useState<BackgroundAsset[]>([]);
  const [busy, setBusy] = useState(false);
  const [pendingAsset, setPendingAsset] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [section, setSection] = useState<"channels" | "batches" | "subtitle-styles" | "thumbnail-styles" | "settings">("channels");
  const [startupReady, setStartupReady] = useState(false);
  const [startupStage, setStartupStage] = useState<StartupStage>("local-tools");
  const [startupError, setStartupError] = useState<string | null>(null);
  const [startupRetry, setStartupRetry] = useState(0);
  const [toolchain, setToolchain] = useState<{ local: LocalToolchainState; dynamic: DynamicToolchainState } | null>(null);

  const selected = channels.find((channel) => channel.id === selectedId) ?? null;
  const filteredChannels = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return channels;
    return channels.filter((channel) => channel.name.toLowerCase().includes(normalized));
  }, [channels, query]);
  const readyAssets = assets.filter((asset) => asset.available).length;

  async function refresh(preferredId?: string | null): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      const nextChannels = await workerRequest<Channel[]>("channels.list");
      const nextSelectedId = preferredId === undefined ? selectedId : preferredId;
      const selectedChannel = nextChannels.find((channel) => channel.id === nextSelectedId)
        ?? nextChannels.find((channel) => channel.active)
        ?? nextChannels[0]
        ?? null;
      setChannels(nextChannels);
      setSelectedId(selectedChannel?.id ?? null);
      setOcrLanguages(await workerRequest<OcrLanguage[]>("thumbnail.ocr.languages").catch(() => []));
      if (selectedChannel) {
        setSubtitleLanguagesText(selectedChannel.subtitle_languages.join(", "));
        setThumbnailLanguagesText(selectedChannel.ocr_languages.join(", "));
        const [nextAssets, nextThumbnailPresets] = await Promise.all([
          workerRequest<BackgroundAsset[]>("backgrounds.list", { channel_id: selectedChannel.id }),
          workerRequest<ThumbnailPreset[]>("thumbnail.presets.list", { channel_id: selectedChannel.id }),
        ]);
        setAssets(nextAssets);
        setThumbnailPresets(nextThumbnailPresets);
      } else {
        setSubtitleLanguagesText("");
        setThumbnailLanguagesText("");
        setAssets([]);
        setThumbnailPresets([]);
      }
      setConnected(true);
      return true;
    } catch (caught) {
      setError(String(caught));
      setConnected(false);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function selectChannel(channelId: string) {
    setSelectedId(channelId);
    setError(null);
    try {
      const channel = channels.find((item) => item.id === channelId);
      setSubtitleLanguagesText(channel?.subtitle_languages.join(", ") ?? "");
      setThumbnailLanguagesText(channel?.ocr_languages.join(", ") ?? "");
      const [nextAssets, nextThumbnailPresets] = await Promise.all([
        workerRequest<BackgroundAsset[]>("backgrounds.list", { channel_id: channelId }),
        workerRequest<ThumbnailPreset[]>("thumbnail.presets.list", { channel_id: channelId }),
      ]);
      setAssets(nextAssets);
      setThumbnailPresets(nextThumbnailPresets);
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function saveSubtitleLanguages() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const languages = subtitleLanguagesText.split(/[\s,;]+/).filter(Boolean);
      await workerRequest<Channel>("channels.set_subtitle_languages", {
        channel_id: selected.id,
        languages,
      });
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
  }

  async function saveThumbnailSettings() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<Channel>("channels.set_thumbnail_settings", {
        channel_id: selected.id,
        mode: selected.thumbnail_mode,
        languages: thumbnailLanguagesText.split(/[\s,;]+/).filter(Boolean),
      });
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
  }

  async function setThumbnailMode(mode: ThumbnailMode) {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<Channel>("channels.set_thumbnail_settings", {
        channel_id: selected.id,
        mode,
        languages: thumbnailLanguagesText.split(/[\s,;]+/).filter(Boolean),
      });
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
  }

  async function setDefaultThumbnailPreset(presetId: string) {
    if (!selected || !presetId) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<Channel>("channels.set_default_thumbnail_preset", { channel_id: selected.id, preset_id: presetId });
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    async function prepareWorkspace() {
      setStartupReady(false);
      setStartupError(null);
      setStartupStage("local-tools");
      try {
        const local = await workerRequest<LocalToolchainState>("system.toolchain.check");
        if (!active) return;
        setStartupStage("dynamic-tools");
        const dynamic = await workerRequest<DynamicToolchainState>("system.ytdlp.sync");
        if (!active) return;
        setToolchain({ local, dynamic });
        setStartupStage("workspace");
        const loaded = await refresh(null);
        if (!loaded) throw new Error("The local workspace could not be loaded. Retry setup to try again.");
        if (active) setStartupReady(true);
      } catch (caught) {
        if (active) setStartupError(String(caught));
      }
    }
    void prepareWorkspace();
    return () => { active = false; };
    // Run bootstrap once per explicit retry. The workspace appears only after every step succeeds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startupRetry]);

  useEffect(() => {
    if (!startupReady) return;
    const sendHeartbeat = () => { void workerRequest("queue.heartbeat").catch(() => undefined); };
    sendHeartbeat();
    const timer = window.setInterval(sendHeartbeat, 4000);
    return () => window.clearInterval(timer);
  }, [startupReady]);

  if (!startupReady) {
    return <StartupSplash stage={startupStage} error={startupError} onRetry={() => setStartupRetry((value) => value + 1)} />;
  }

  function startDialog(mode: Exclude<DialogMode, null>) {
    setError(null);
    if (mode === "edit") setChannelName(selected?.name ?? "");
    else if (mode === "duplicate") setChannelName(selected ? `${selected.name} copy` : "");
    else setChannelName("");
    setDialog(mode);
  }

  async function submitChannel(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!channelName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      if (dialog === "create") {
        const created = await workerRequest<Channel>("channels.create", { name: channelName });
        setDialog(null);
        await refresh(created.id);
      } else if (dialog === "edit" && selected) {
        await workerRequest<Channel>("channels.update", { channel_id: selected.id, name: channelName });
        setDialog(null);
        await refresh(selected.id);
      } else if (dialog === "duplicate" && selected) {
        const copy = await workerRequest<Channel>("channels.duplicate", {
          channel_id: selected.id,
          name: channelName,
        });
        setDialog(null);
        await refresh(copy.id);
      }
    } catch (caught) {
      setError(String(caught));
      setBusy(false);
    }
  }

  async function toggleChannel(channel: Channel) {
    try {
      await workerRequest<Channel>("channels.set_active", {
        channel_id: channel.id,
        active: !channel.active,
      });
      await refresh(channel.id === selectedId && channel.active ? null : channel.id);
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function addBackgroundFiles() {
    setError(null);
    if (!selected) return;
    try {
      const picked = await open({
        multiple: true,
        title: "Add background videos",
        filters: [{ name: "Video files", extensions: ["mp4", "mov", "mkv", "webm", "m4v", "avi"] }],
      });
      if (!picked) return;
      const paths = Array.isArray(picked) ? picked : [picked];
      setBusy(true);
      for (const path of paths) {
        await workerRequest<BackgroundAsset>("backgrounds.add_to_channel", {
          channel_id: selected.id,
          path,
        });
      }
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function openLibrary() {
    setError(null);
    try {
      setLibrary(await workerRequest<BackgroundAsset[]>("backgrounds.library"));
      setDialog("library");
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function assignAsset(asset: BackgroundAsset) {
    if (!selected) return;
    setPendingAsset(asset.id);
    setError(null);
    try {
      await workerRequest("backgrounds.assign_to_channel", {
        channel_id: selected.id,
        asset_id: asset.id,
      });
      setLibrary(await workerRequest<BackgroundAsset[]>("backgrounds.library"));
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setPendingAsset(null);
    }
  }

  async function removeAsset(asset: BackgroundAsset) {
    if (!selected) return;
    setPendingAsset(asset.id);
    setError(null);
    try {
      await workerRequest("backgrounds.remove_from_channel", {
        channel_id: selected.id,
        asset_id: asset.id,
      });
      await refresh(selected.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setPendingAsset(null);
    }
  }

  async function relinkAsset(asset: BackgroundAsset) {
    setError(null);
    try {
      const picked = await open({
        multiple: false,
        title: "Locate missing background video",
        filters: [{ name: "Video files", extensions: ["mp4", "mov", "mkv", "webm", "m4v", "avi"] }],
      });
      if (typeof picked !== "string") return;
      setPendingAsset(asset.id);
      await workerRequest<BackgroundAsset>("backgrounds.relink_asset", {
        asset_id: asset.id,
        path: picked,
      });
      await refresh(selected?.id);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setPendingAsset(null);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark"><FilmSlate size={19} weight="fill" /></div>
          <div className="brand-name">frame<span>work</span><small>VIDEO STUDIO</small></div>
        </div>

        <div className="side-section-heading">
          <span>WORKSPACE</span>
          <span className={`connection-dot ${connected ? "is-online" : ""}`} title={connected ? "Worker connected" : "Connecting to local worker"} />
        </div>
        <button className={`workspace-link ${section === "channels" ? "is-current" : ""}`} type="button" onClick={() => setSection("channels")}>
          <Stack size={17} weight="duotone" />
          <span>Channel library</span>
          {section === "channels" && <ArrowDownRight className="nav-arrow" size={14} />}
        </button>
        <button className={`workspace-link batch-nav-link ${section === "batches" ? "is-current" : ""}`} type="button" onClick={() => setSection("batches")}>
          <VideoCamera size={17} weight="duotone" />
          <span>Batch planning</span>
          {section === "batches" && <ArrowDownRight className="nav-arrow" size={14} />}
        </button>
        <button className={`workspace-link subtitle-nav-link ${section === "subtitle-styles" ? "is-current" : ""}`} type="button" onClick={() => setSection("subtitle-styles")}>
          <TextT size={17} weight="duotone" />
          <span>Subtitle styles</span>
          {section === "subtitle-styles" && <ArrowDownRight className="nav-arrow" size={14} />}
        </button>
        <button className={`workspace-link thumbnail-nav-link ${section === "thumbnail-styles" ? "is-current" : ""}`} type="button" onClick={() => setSection("thumbnail-styles")}>
          <ImageSquare size={17} weight="duotone" />
          <span>Thumbnail styles</span>
          {section === "thumbnail-styles" && <ArrowDownRight className="nav-arrow" size={14} />}
        </button>
        <button className={`workspace-link settings-nav-link ${section === "settings" ? "is-current" : ""}`} type="button" onClick={() => setSection("settings")}>
          <GearSix size={17} weight="duotone" />
          <span>Settings</span>
          {section === "settings" && <ArrowDownRight className="nav-arrow" size={14} />}
        </button>
        <div className="channel-list-head">
          <span>CHANNELS <b>{channels.length}</b></span>
          <button aria-label="Create channel" className="icon-button on-dark" onClick={() => startDialog("create")} type="button"><Plus size={16} /></button>
        </div>
        <label className="channel-search">
          <MagnifyingGlass size={14} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a channel" />
          {query && <button type="button" aria-label="Clear search" onClick={() => setQuery("")}><X size={13} /></button>}
        </label>
        <div className="channel-list">
          {filteredChannels.map((channel, index) => (
            <button
              className={`channel-item ${selectedId === channel.id ? "is-selected" : ""} ${!channel.active ? "is-archived" : ""}`}
              key={channel.id}
              onClick={() => void selectChannel(channel.id)}
              type="button"
            >
              <span className={`channel-avatar avatar-${index % 5}`}>{channel.name.trim().charAt(0).toUpperCase()}</span>
              <span className="channel-name">{channel.name}<small>{channel.background_count} backgrounds</small></span>
              {!channel.active && <span className="archived-dot" title="Archived" />}
            </button>
          ))}
          {filteredChannels.length === 0 && (
            <div className="sidebar-empty">{query ? "No channels match." : "Your channels will appear here."}</div>
          )}
        </div>

        <div className="sidebar-bottom">
          <div className="local-note"><span className="local-note-icon"><FolderOpen size={15} /></span><span>LOCAL LIBRARY<small>Files stay on this device</small></span></div>
          <div className="version-note">YouTube Video Batch Tool <span>0.1.0</span></div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>{section === "channels" ? "Channel library" : section === "batches" ? "Batch planning" : section === "subtitle-styles" ? "Subtitle styles" : section === "thumbnail-styles" ? "Thumbnail styles" : "Settings"}</strong></div>
          <div className="topbar-right">
            <div className="worker-status"><span className={`status-light ${connected ? "online" : ""}`} />{connected ? "Worker ready" : "Worker offline"}</div>
            <span className="topbar-divider" />
            <div className="profile-chip"><span className="profile-avatar">LD</span><span>Local workspace</span></div>
          </div>
        </header>

        <div className="page-content">
          {error && <div className="error-banner"><WarningCircle size={18} /><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss"><X size={15} /></button></div>}
          {section === "settings" && toolchain ? <SettingsWorkspace localTools={toolchain.local} dynamicTools={toolchain.dynamic} /> : section === "batches" ? <BatchWorkspace /> : section === "subtitle-styles" ? <SubtitleStylesWorkspace /> : section === "thumbnail-styles" ? <ThumbnailStylesWorkspace channels={channels} selectedChannelId={selected?.id ?? null} onRefresh={() => void refresh(selected?.id)} /> : !selected ? (
            <section className="welcome-state">
              <div className="welcome-orbit orbit-one" /><div className="welcome-orbit orbit-two" />
              <div className="welcome-icon"><VideoCamera size={28} weight="duotone" /></div>
              <span className="eyebrow">YOUR PRODUCTION WORKSPACE</span>
              <h1>Start with a channel.</h1>
              <p>Create a profile for each channel, then collect the background videos you want to rotate through.</p>
              <button className="button button-primary" type="button" onClick={() => startDialog("create")}><Plus size={17} weight="bold" /> Create first channel</button>
              <div className="welcome-footnote"><CheckCircle size={15} /> Saved locally on your Mac</div>
            </section>
          ) : (
            <>
              <div className="page-heading-row">
                <div>
                  <div className="eyebrow page-kicker">CHANNEL PROFILE <span className={`active-tag ${selected.active ? "" : "inactive"}`}><span />{selected.active ? "Active" : "Archived"}</span></div>
                  <h1>{selected.name}</h1>
                  <p className="heading-description">Organize this channel’s reusable footage pool.</p>
                </div>
                <div className="heading-actions">
                  <button className="button button-secondary" type="button" onClick={() => startDialog("edit")}><PencilSimple size={16} /> Edit profile</button>
                  <button className="button button-secondary" type="button" onClick={() => startDialog("duplicate")}><CopySimple size={16} /> Duplicate</button>
                  <button className="button button-quiet" type="button" onClick={() => void toggleChannel(selected)}><Archive size={16} /> {selected.active ? "Archive" : "Reactivate"}</button>
                </div>
              </div>

              <section className="pool-summary">
                <div className="summary-icon"><FilmSlate size={19} weight="duotone" /></div>
                <div className="summary-copy"><strong>Background pool</strong><span>Videos are assigned to this channel and can also be shared with others.</span></div>
                <div className="summary-stat"><strong>{assets.length}</strong><span>IN POOL</span></div>
                <div className="summary-stat"><strong>{readyAssets}</strong><span>AVAILABLE</span></div>
                <div className="summary-divider" />
                <button className="button button-secondary library-button" type="button" onClick={() => void openLibrary()}><FolderOpen size={16} /> Browse library</button>
                <button className="button button-primary" type="button" onClick={() => void addBackgroundFiles()} disabled={busy}><Plus size={17} weight="bold" /> Add videos</button>
              </section>

              <section className="subtitle-language-settings">
                <div><strong>Preferred subtitle languages</strong><span>Order matters. For each language, creator captions are preferred over YouTube auto captions.</span></div>
                <input aria-label="Preferred subtitle languages, in order" value={subtitleLanguagesText} onChange={(event) => setSubtitleLanguagesText(event.target.value)} placeholder="e.g. en, vi, fr-CA" />
                <button className="button button-secondary" type="button" onClick={() => void saveSubtitleLanguages()} disabled={busy}><Check size={15} /> Save languages</button>
              </section>

              <section className="thumbnail-channel-settings">
                <div className="thumbnail-settings-heading">
                  <div><strong>Thumbnail workflow</strong><span>OCR reads text from the downloaded source thumbnail. It never uses the video title.</span></div>
                  <select aria-label="Thumbnail workflow mode" value={selected.thumbnail_mode} onChange={(event) => void setThumbnailMode(event.target.value as ThumbnailMode)} disabled={busy}>
                    <option value="auto">Auto · OCR + preset export</option>
                    <option value="manual">Manual · save source image</option>
                    <option value="skip">Skip thumbnails</option>
                  </select>
                </div>
                {selected.thumbnail_mode === "auto" && <>
                  <label className="thumbnail-language-field"><span>OCR languages</span><input aria-label="Thumbnail OCR languages" value={thumbnailLanguagesText} onChange={(event) => setThumbnailLanguagesText(event.target.value)} placeholder="eng, vie" /><small>Installed: {ocrLanguages.length ? ocrLanguages.map((language) => language.code).join(", ") : "Tesseract language data not detected"}</small></label>
                  <label className="thumbnail-language-field default-thumbnail-field"><span>Default style</span><select aria-label="Default thumbnail style" value={selected.default_thumbnail_preset_id ?? ""} onChange={(event) => void setDefaultThumbnailPreset(event.target.value)} disabled={busy}><option value="" disabled>Choose a preset</option>{thumbnailPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select><small>{selected.thumbnail_preset_count} styles in this channel’s rotation pool.</small></label>
                  <button className="button button-secondary thumbnail-save-button" type="button" onClick={() => void saveThumbnailSettings()} disabled={busy}><Check size={15} /> Save OCR languages</button>
                </>}
                {selected.thumbnail_mode === "manual" && <p className="thumbnail-mode-note">Source thumbnail được lưu cạnh audio để bạn tự chỉnh bằng Canva hoặc app khác. Chế độ này không chạy OCR hay tạo PNG.</p>}
                {selected.thumbnail_mode === "skip" && <p className="thumbnail-mode-note">Ứng dụng sẽ không tải hoặc xử lý thumbnail cho job của channel này.</p>}
              </section>

              {assets.length > 0 ? (
                <>
                  <div className="section-heading"><div><h2>Pool videos</h2><span>{assets.length} {assets.length === 1 ? "video" : "videos"} assigned</span></div><div className="section-tools"><span className="sort-label">ADDED TO LIBRARY</span></div></div>
                  <div className="asset-grid">
                    {assets.map((asset, index) => (
                      <article className={`asset-card ${!asset.available ? "asset-missing" : ""}`} key={asset.id}>
                        <div className={`asset-preview preview-${index % 4}`}>
                          <div className="preview-grid" />
                          <div className="preview-orb" />
                          <div className="preview-file-mark"><FilmSlate size={23} weight="duotone" /></div>
                          <span className="duration-pill">{formatDuration(asset.duration_seconds)}</span>
                          {!asset.available && <span className="missing-pill"><WarningCircle size={12} /> File missing</span>}
                        </div>
                        <div className="asset-details">
                          <div className="asset-title-line"><h3 title={asset.name}>{asset.name}</h3><button type="button" title="Remove from this channel" aria-label={`Remove ${asset.name} from this channel`} className="remove-asset" disabled={pendingAsset === asset.id} onClick={() => void removeAsset(asset)}><X size={15} /></button></div>
                          <div className="asset-path" title={asset.path}>{asset.path}</div>
                          <div className="asset-meta">
                            <span>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "Size unavailable"}</span>
                            <i />
                            <span>{formatFrameRate(asset.frame_rate)}</span>
                            <span className={`probe-state ${asset.probe_status === "ready" ? "good" : ""}`} title={asset.probe_status === "ready" ? asset.codec ?? "Metadata read" : "ffprobe could not read all metadata"}>{asset.probe_status === "ready" ? <Check size={12} /> : <WarningCircle size={12} />}</span>
                          </div>
                          {!asset.available && <button className="relink-button" type="button" onClick={() => void relinkAsset(asset)} disabled={pendingAsset === asset.id}><FolderOpen size={13} />{pendingAsset === asset.id ? "Relinking…" : "Locate file"}<span>Updates this shared library item</span></button>}
                        </div>
                      </article>
                    ))}
                    <button className="add-card" type="button" onClick={() => void addBackgroundFiles()} disabled={busy}>
                      <span className="add-card-icon"><Plus size={19} /></span><strong>Add another video</strong><small>Choose one or more local files</small>
                    </button>
                  </div>
                </>
              ) : (
                <section className="empty-pool">
                  <div className="empty-stack"><FilmSlate size={22} weight="duotone" /><span><Plus size={14} /></span></div>
                  <h2>No backgrounds assigned yet</h2>
                  <p>Add local video files or reuse footage already in your library.</p>
                  <div className="empty-actions"><button className="button button-primary" type="button" onClick={() => void addBackgroundFiles()} disabled={busy}><Plus size={16} /> Add videos</button><button className="button button-secondary" type="button" onClick={() => void openLibrary()}><FolderOpen size={16} /> Choose from library</button></div>
                </section>
              )}

              <div className="storage-footnote"><span className="storage-dot" /><span>Background files are referenced in place. They are not copied into the app.</span><button type="button" title="Refresh library" onClick={() => void refresh(selected.id)} disabled={busy}><CircleNotch className={busy ? "spin" : ""} size={15} /></button></div>
            </>
          )}
        </div>
      </main>

      {dialog && dialog !== "library" && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(null); }}>
          <form className="modal-card compact-modal" onSubmit={submitChannel}>
            <div className="modal-head"><div><span className="eyebrow">CHANNEL PROFILE</span><h2>{dialog === "create" ? "Create a channel" : dialog === "edit" ? "Edit channel" : "Duplicate channel"}</h2></div><button type="button" className="modal-close" aria-label="Close" onClick={() => setDialog(null)}><X size={18} /></button></div>
            <label className="field-label" htmlFor="channel-name">Channel name</label>
            <input id="channel-name" className="text-input" autoFocus value={channelName} onChange={(event) => setChannelName(event.target.value)} placeholder="e.g. Quiet Rain Stories" maxLength={80} />
            {dialog === "duplicate" && <p className="modal-note">The background pool will be copied. Source files stay shared in the local library.</p>}
            <div className="modal-actions"><button type="button" className="button button-secondary" onClick={() => setDialog(null)}>Cancel</button><button type="submit" className="button button-primary" disabled={busy || !channelName.trim()}>{busy ? <CircleNotch className="spin" size={16} /> : <Check size={16} />}{dialog === "create" ? "Create channel" : dialog === "edit" ? "Save changes" : "Create duplicate"}</button></div>
          </form>
        </div>
      )}

      {dialog === "library" && selected && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDialog(null); }}>
          <section className="modal-card library-modal">
            <div className="modal-head"><div><span className="eyebrow">SHARED MEDIA</span><h2>Background library</h2><p>Assign saved files to <strong>{selected.name}</strong>. One file can belong to several channels.</p></div><button type="button" className="modal-close" aria-label="Close" onClick={() => setDialog(null)}><X size={18} /></button></div>
            <div className="library-list">
              {library.length === 0 ? <div className="library-empty"><FolderOpen size={22} /><strong>Your library is empty</strong><span>Add a background video to any channel to save it here.</span></div> : library.map((asset) => {
                const assigned = asset.channel_ids?.includes(selected.id) ?? false;
                return <div className="library-row" key={asset.id}><div className="library-file-icon"><FilmSlate size={18} weight="duotone" /></div><div className="library-file-copy"><strong title={asset.name}>{asset.name}</strong><span>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "Dimensions unavailable"} · {formatDuration(asset.duration_seconds)} · used by {asset.channel_ids?.length ?? 0} {(asset.channel_ids?.length ?? 0) === 1 ? "channel" : "channels"}</span></div>{assigned ? <span className="assigned-label"><CheckCircle size={15} /> Assigned</span> : <button className="button button-secondary library-assign" type="button" onClick={() => void assignAsset(asset)} disabled={!asset.available || pendingAsset === asset.id}>{pendingAsset === asset.id ? <CircleNotch className="spin" size={15} /> : <Plus size={15} />} Assign</button>}</div>;
              })}
            </div>
            <div className="modal-actions library-footer"><span>Missing files stay in the library and can be relinked later.</span><button className="button button-primary" type="button" onClick={() => setDialog(null)}>Done</button></div>
          </section>
        </div>
      )}
    </div>
  );
}

export default App;
