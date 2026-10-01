import { CheckCircle, CircleNotch, FilmSlate, WarningCircle } from "@phosphor-icons/react";

export type StartupStage = "local-tools" | "dynamic-tools" | "workspace";

type Props = { stage: StartupStage; error: string | null; onRetry: () => void };

const stages: { id: StartupStage; title: string }[] = [
  { id: "local-tools", title: "Checking packaged media and OCR tools" },
  { id: "dynamic-tools", title: "Checking and updating YouTube tools" },
  { id: "workspace", title: "Loading your local workspace" },
];

export default function StartupSplash({ stage, error, onRetry }: Props) {
  const activeIndex = stages.findIndex((item) => item.id === stage);

  return (
    <main className="startup-splash">
      <div className="startup-glow startup-glow-one" /><div className="startup-glow startup-glow-two" />
      <section className="startup-card">
        <div className="startup-brand-mark"><FilmSlate size={25} weight="fill" /></div>
        <div className="startup-brand-name">frame<span>work</span><small>VIDEO STUDIO</small></div>
        <span className="startup-eyebrow">LOCAL WORKSPACE · FIRST-RUN CHECK</span>
        <h1>{error ? "Setup needs attention" : "Preparing your workspace"}</h1>
        <p className="startup-summary">The app checks its media tools and updates yt-dlp automatically before opening.</p>

        <div className="startup-progress-list">
          {stages.map((item, index) => {
            const complete = !error && index < activeIndex;
            const current = !error && index === activeIndex;
            return <div className={`startup-progress-item ${complete ? "is-complete" : ""} ${current ? "is-current" : ""}`} key={item.id}>
              <span className="startup-step-icon">{complete ? <CheckCircle size={17} weight="fill" /> : current ? <CircleNotch className="spin" size={16} /> : <span>{String(index + 1).padStart(2, "0")}</span>}</span>
              <span>{item.title}</span>
            </div>;
          })}
        </div>

        {error ? <div className="startup-error"><WarningCircle size={17} /><span>{error}</span><button className="button button-primary" type="button" onClick={onRetry}>Retry setup</button></div>
          : <div className="startup-working"><CircleNotch className="spin" size={15} /> This may take a moment on first launch.</div>}
        <div className="startup-local-note">Your media and settings stay on this device.</div>
      </section>
    </main>
  );
}
