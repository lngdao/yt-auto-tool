import { useEffect, useState } from "react";
import { CheckCircle, CircleNotch, FolderOpen, ShieldWarning, WarningCircle } from "@phosphor-icons/react";
import { open } from "@tauri-apps/plugin-dialog";
import { DynamicToolchainState, LocalToolchainState, OutputDirectorySettings, YoutubeCookieSettings, workerRequest } from "./worker";

type Props = { localTools: LocalToolchainState; dynamicTools: DynamicToolchainState };

function fileName(path: string) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

export default function SettingsWorkspace({ localTools, dynamicTools }: Props) {
  const [cookies, setCookies] = useState<YoutubeCookieSettings | null>(null);
  const [outputDirectory, setOutputDirectory] = useState<OutputDirectorySettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshCookies() {
    setCookies(await workerRequest<YoutubeCookieSettings>("settings.youtube_cookies.get"));
  }

  async function refreshOutputDirectory() {
    setOutputDirectory(await workerRequest<OutputDirectorySettings>("settings.output_directory.get"));
  }

  useEffect(() => {
    void refreshCookies().catch((caught) => setError(String(caught)));
    void refreshOutputDirectory().catch((caught) => setError(String(caught)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function chooseOutputDirectory() {
    setError(null);
    try {
      const path = await open({ directory: true, multiple: false, title: "Choose the default output folder" });
      if (typeof path !== "string") return;
      setBusy(true);
      setOutputDirectory(await workerRequest<OutputDirectorySettings>("settings.output_directory.set", { path }));
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function clearOutputDirectory() {
    setBusy(true);
    setError(null);
    try {
      setOutputDirectory(await workerRequest<OutputDirectorySettings>("settings.output_directory.set", { path: null }));
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function chooseCookies() {
    setError(null);
    try {
      const path = await open({
        multiple: false,
        title: "Choose exported YouTube cookies.txt",
        filters: [{ name: "Netscape cookies.txt", extensions: ["txt"] }],
      });
      if (typeof path !== "string") return;
      setBusy(true);
      setCookies(await workerRequest<YoutubeCookieSettings>("settings.youtube_cookies.set", { path }));
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function clearCookies() {
    setBusy(true);
    setError(null);
    try {
      setCookies(await workerRequest<YoutubeCookieSettings>("settings.youtube_cookies.set", { path: null }));
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  const invalidCookie = cookies?.configured && (!cookies.available || !cookies.valid_format);
  const tools = [
    { label: "yt-dlp", version: dynamicTools.yt_dlp.version, note: dynamicTools.yt_dlp.updated ? "Updated automatically this launch" : `Latest stable: ${dynamicTools.yt_dlp.latest_version}` },
    { label: "Deno", version: dynamicTools.deno.version, note: dynamicTools.deno.updated ? "Updated automatically this launch" : `Latest stable: ${dynamicTools.deno.latest_version}` },
    { label: "FFmpeg", version: localTools.ffmpeg.version, note: "H.264, AAC and subtitles filter ready" },
    { label: "ffprobe", version: localTools.ffprobe.version, note: "Media inspection ready" },
    { label: "Tesseract OCR", version: localTools.tesseract.version, note: `Models: ${(localTools.tesseract.languages ?? []).join(", ")}` },
  ];

  return (
    <section className="settings-workspace">
      <div className="page-heading-row settings-heading">
        <div>
          <div className="eyebrow page-kicker">LOCAL APP CONFIGURATION</div>
          <h1>Settings</h1>
          <p className="heading-description">Set output defaults, manage YouTube access, and check workspace tools.</p>
        </div>
      </div>

      {error && <div className="error-banner"><WarningCircle size={18} /><span>{error}</span></div>}

      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>Default output folder</h2><p>Used for new batches unless a batch has its own folder. All videos in a batch share this root.</p></div>
          <span className={`settings-status ${outputDirectory?.configured && outputDirectory.available ? "is-ready" : outputDirectory?.configured ? "is-warning" : ""}`}>
            {outputDirectory?.configured && outputDirectory.available ? <CheckCircle size={14} /> : outputDirectory?.configured ? <WarningCircle size={14} /> : null}
            {outputDirectory?.configured ? outputDirectory.available ? "Ready" : "Unavailable" : "Optional"}
          </span>
        </div>
        <div className="cookie-setting-row">
          <div className="cookie-file-icon"><FolderOpen size={19} /></div>
          <div className="cookie-file-copy">
            <strong>{outputDirectory?.configured ? fileName(outputDirectory.path ?? "") : "No default folder selected"}</strong>
            <span title={outputDirectory?.path ?? undefined}>
              {outputDirectory?.configured
                ? outputDirectory.available ? outputDirectory.path : "This folder is not available. Choose another folder."
                : "Choose a root such as D:\\YT. A batch can override it without changing this default."}
            </span>
          </div>
          <button className="button button-secondary" type="button" onClick={() => void chooseOutputDirectory()} disabled={busy}>
            {busy ? <CircleNotch className="spin" size={15} /> : <FolderOpen size={15} />}
            {outputDirectory?.configured ? "Change folder" : "Choose folder"}
          </button>
          {outputDirectory?.configured && <button className="button button-quiet" type="button" onClick={() => void clearOutputDirectory()} disabled={busy}>Clear</button>}
        </div>
      </section>

      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>YouTube cookies</h2><p>Use an exported browser session if YouTube asks yt-dlp to sign in.</p></div>
          <span className={`settings-status ${invalidCookie ? "is-warning" : cookies?.configured ? "is-ready" : ""}`}>
            {invalidCookie ? <WarningCircle size={14} /> : cookies?.configured ? <CheckCircle size={14} /> : null}
            {invalidCookie ? "Needs attention" : cookies?.configured ? "Configured" : "Optional"}
          </span>
        </div>
        <div className="cookie-setting-row">
          <div className="cookie-file-icon"><FolderOpen size={19} /></div>
          <div className="cookie-file-copy">
            <strong>{cookies?.configured ? fileName(cookies.path ?? "cookies.txt") : "No cookies file selected"}</strong>
            <span title={cookies?.path ?? undefined}>
              {invalidCookie
                ? "The saved file is missing or is not a valid Netscape cookies.txt export."
                : cookies?.configured
                  ? cookies.path
                  : "YouTube videos that do not need an account can still download without cookies."}
            </span>
          </div>
          <button className="button button-secondary" type="button" onClick={() => void chooseCookies()} disabled={busy}>
            {busy ? <CircleNotch className="spin" size={15} /> : <FolderOpen size={15} />}
            {cookies?.configured ? "Choose another" : "Choose cookies.txt"}
          </button>
          {cookies?.configured && <button className="button button-quiet" type="button" onClick={() => void clearCookies()} disabled={busy}>Clear</button>}
        </div>
        <p className="settings-security-note"><ShieldWarning size={15} /> Export with <strong>Get cookies.txt LOCALLY</strong>. The app stores only this local path and passes the file to yt-dlp; cookie contents are not copied or uploaded. Treat the export like a password.</p>
      </section>

      <section className="settings-section">
        <div className="settings-section-heading">
          <div><h2>Startup toolchain</h2><p>yt-dlp and Deno update automatically before the workspace opens.</p></div>
          <span className="settings-status is-ready"><CheckCircle size={14} /> Ready</span>
        </div>
        <div className="toolchain-grid">
          {tools.map((tool) => (
            <article className="toolchain-card" key={tool.label}>
              <span className="toolchain-dot" />
              <div><strong>{tool.label}</strong><code>{tool.version}</code><small>{tool.note}</small></div>
            </article>
          ))}
        </div>
        <p className="settings-footnote">Updates are fetched from official release assets and verified before replacing the app-data copy. FFmpeg and Tesseract are bundled with the app and checked at startup.</p>
      </section>
    </section>
  );
}
