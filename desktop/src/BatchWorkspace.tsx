import { ChangeEvent, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  Check,
  CheckCircle,
  CircleNotch,
  FilmSlate,
  FolderOpen,
  ImageSquare,
  MagnifyingGlass,
  Plus,
  Repeat,
  Trash,
  VideoCamera,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { open } from "@tauri-apps/plugin-dialog";
import { revealItemInDir } from "@tauri-apps/plugin-opener";
import { BackgroundAsset, BatchSummary, BatchView, Channel, OutputProfile, QueueStatus, QueueTask, RenderPlan, ThumbnailMode, ThumbnailPreset, VideoJob, workerRequest } from "./worker";
import "./BatchWorkspace.css";

type ImportMode = "paste" | "file";
type WorkflowMode = "render" | "download_only";

function formatTime(seconds: number | null) {
  if (seconds === null) return "—";
  const total = Math.floor(seconds);
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, "0")}`;
}

function readinessLabel(job: VideoJob) {
  if (job.readiness === "ready") return "Ready";
  if (job.readiness === "needs_metadata") return "Fetch details";
  if (job.readiness === "unknown_channel") return "Choose channel";
  if (job.readiness === "duplicate_url") return "Duplicate URL";
  if (job.readiness === "invalid_url") return "Invalid URL";
  if (job.readiness === "no_background_pool") return "No background pool";
  if (job.readiness === "background_unassigned") return "Assign background";
  if (job.readiness === "missing_background_file") return "Background missing";
  if (job.readiness === "metadata_error") return "Metadata error";
  return job.readiness.replace(/_/g, " ");
}

export default function BatchWorkspace() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [batches, setBatches] = useState<BatchSummary[]>([]);
  const [backgroundPools, setBackgroundPools] = useState<Record<string, BackgroundAsset[]>>({});
  const [current, setCurrent] = useState<BatchView | null>(null);
  const [queueTasks, setQueueTasks] = useState<QueueTask[]>([]);
  const [queueConcurrency, setQueueConcurrency] = useState(1);
  const [composer, setComposer] = useState(false);
  const [importMode, setImportMode] = useState<ImportMode>("paste");
  const [workflowMode, setWorkflowMode] = useState<WorkflowMode>("render");
  const [channelId, setChannelId] = useState("");
  const [batchName, setBatchName] = useState("");
  const [urlText, setUrlText] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [fileName, setFileName] = useState("");
  const [selectedJobs, setSelectedJobs] = useState<string[]>([]);
  const [bulkAssetId, setBulkAssetId] = useState("");
  const [bulkOutput, setBulkOutput] = useState<OutputProfile>({ profile: "720p", frame_preference: "profile", fit_mode: "crop" });
  const [batchThumbnailPresetIds, setBatchThumbnailPresetIds] = useState<string[]>([]);
  const [urlEdits, setUrlEdits] = useState<Record<string, string>>({});
  const [subtitleJobId, setSubtitleJobId] = useState<string | null>(null);
  const [subtitleOverrideText, setSubtitleOverrideText] = useState("");
  const [renderJobId, setRenderJobId] = useState<string | null>(null);
  const [renderPlan, setRenderPlan] = useState<RenderPlan | null>(null);
  const [renderSettings, setRenderSettings] = useState<OutputProfile>({ profile: "720p", frame_preference: null, fit_mode: "crop" });
  const [renderingJobId, setRenderingJobId] = useState<string | null>(null);
  const [thumbnailJobId, setThumbnailJobId] = useState<string | null>(null);
  const [thumbnailText, setThumbnailText] = useState("");
  const [queueLogTaskId, setQueueLogTaskId] = useState<string | null>(null);
  const [outputDirectory, setOutputDirectory] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const isDraft = current?.batch.state === "draft";
  const downloadOnly = current?.batch.workflow_mode === "download_only";
  const selectedJobRows = useMemo(
    () => current?.jobs.filter((job) => selectedJobs.includes(job.id)) ?? [],
    [current, selectedJobs],
  );
  const batchQueueTasks = current?.jobs.flatMap((job) => [job.queue_task, job.download_queue_task, job.thumbnail_queue_task].filter((task): task is NonNullable<typeof task> => Boolean(task))) ?? [];
  const completedQueueTasks = batchQueueTasks.filter((task) => ["complete", "failed", "cancelled", "interrupted"].includes(task.state)).length;
  const batchQueueProgress = batchQueueTasks.length ? batchQueueTasks.reduce((total, task) => total + task.progress, 0) / batchQueueTasks.length : 0;
  const bulkAssetOptions = useMemo(() => {
    if (!selectedJobRows.length || selectedJobRows.some((job) => !job.channel_id)) return [];
    const firstChannel = selectedJobRows[0].channel_id;
    return (backgroundPools[firstChannel ?? ""] ?? []).filter((asset) =>
      asset.available && selectedJobRows.every((job) =>
        (backgroundPools[job.channel_id ?? ""] ?? []).some((candidate) => candidate.id === asset.id && candidate.available),
      ),
    );
  }, [backgroundPools, selectedJobRows]);

  async function refreshList() {
    const [nextChannels, nextBatches] = await Promise.all([
      workerRequest<Channel[]>("channels.list"),
      workerRequest<BatchSummary[]>("batches.list"),
    ]);
    setChannels(nextChannels);
    setBatches(nextBatches);
    const channelAssets = await Promise.all(nextChannels.map(async (channel) => [
      channel.id,
      await workerRequest<BackgroundAsset[]>("backgrounds.list", { channel_id: channel.id }),
    ] as const));
    setBackgroundPools(Object.fromEntries(channelAssets));
  }

  async function refreshBatch(batchId: string) {
    const [next, nextBatches, queue] = await Promise.all([
      workerRequest<BatchView>("batches.get", { batch_id: batchId }),
      workerRequest<BatchSummary[]>("batches.list"),
      workerRequest<QueueStatus>("queue.status", { batch_id: batchId }),
    ]);
    setCurrent(next);
    setBatches(nextBatches);
    setQueueTasks(queue.tasks);
    setQueueConcurrency(queue.runtime.max_concurrency);
    setBatchThumbnailPresetIds(next.batch.thumbnail_preset_ids);
    setSelectedJobs([]);
    setBulkAssetId("");
    setUrlEdits(Object.fromEntries(next.jobs.map((job) => [job.id, job.url])));
  }

  useEffect(() => {
    void refreshList().catch((caught) => setError(String(caught))).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!current || current.batch.state !== "confirmed") return;
    let active = true;
    const updateQueueView = async () => {
      try {
        const [next, status] = await Promise.all([
          workerRequest<BatchView>("batches.get", { batch_id: current.batch.id }),
          workerRequest<QueueStatus>("queue.status", { batch_id: current.batch.id }),
        ]);
        if (active) {
          setCurrent(next);
          setQueueTasks(status.tasks);
          setQueueConcurrency(status.runtime.max_concurrency);
        }
      } catch {
        // A queue worker may be stopping as the app recovers a job; keep the last view until the next poll.
      }
    };
    void updateQueueView();
    const timer = window.setInterval(() => void updateQueueView(), 1100);
    return () => { active = false; window.clearInterval(timer); };
  }, [current?.batch.id, current?.batch.state]);

  function beginNewBatch() {
    setCurrent(null);
    setComposer(true);
    setImportMode("paste");
    setWorkflowMode("render");
    setBatchName("");
    setUrlText("");
    setFileContent("");
    setFileName("");
    setChannelId(channels.find((channel) => channel.active)?.id ?? channels[0]?.id ?? "");
    setError(null);
    setNotice(null);
  }

  async function importBatch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = importMode === "paste" ? urlText : fileContent;
    if (!content.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const appendToBatchId = current?.batch.id;
      const previousJobCount = appendToBatchId ? current?.jobs.length ?? 0 : 0;
      const imported = await workerRequest<BatchView>(appendToBatchId ? "batches.append_text" : "batches.import_text", {
        batch_id: appendToBatchId,
        name: batchName,
        channel_id: importMode === "paste" ? channelId : null,
        content,
        ...(appendToBatchId ? {} : { workflow_mode: workflowMode }),
      });
      if (appendToBatchId) await refreshBatch(appendToBatchId);
      else {
        await refreshList();
        setCurrent(imported);
        setUrlEdits(Object.fromEntries(imported.jobs.map((job) => [job.id, job.url])));
        setSelectedJobs([]);
      }
      setComposer(false);
      const addedCount = Math.max(0, imported.jobs.length - previousJobCount);
      const importedMode = appendToBatchId ? current?.batch.workflow_mode : workflowMode;
      setNotice(importedMode === "download_only" ? `Imported ${addedCount} video ${addedCount === 1 ? "job" : "jobs"}. Review the channel and subtitle choices before confirming.` : `Imported ${addedCount} video ${addedCount === 1 ? "job" : "jobs"}. Review channel and background assignments before confirming.`);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function readImportFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    try {
      setFileName(file.name);
      setFileContent(await file.text());
      setError(null);
    } catch (caught) {
      setError(`Could not read ${file.name}: ${String(caught)}`);
    }
  }

  async function lookupMetadata() {
    if (!current) return;
    setBusy(true);
    setError(null);
    setNotice("Looking up video details with yt-dlp. This reads metadata only and does not download the source video.");
    try {
      const result = await workerRequest<VideoJob[]>("batches.lookup_metadata", { batch_id: current.batch.id });
      await refreshBatch(current.batch.id);
      const failed = result.filter((job) => job.metadata_status === "error").length;
      setNotice(failed ? `Lookup finished. ${failed} job(s) need attention; inspect their metadata errors below.` : "Video details loaded. Review the planned assignments before confirming.");
    } catch (caught) {
      setError(String(caught));
      setNotice(null);
    } finally {
      setBusy(false);
    }
  }

  async function rebalance() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<BatchView>("batches.rebalance_backgrounds", { batch_id: current.batch.id });
      await refreshBatch(current.batch.id);
      setNotice("Background assignments balanced again. Manual overrides remain locked.");
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function updateJob(job: VideoJob, changes: { url?: string; channel_id?: string | null }) {
    if (!current) return;
    setError(null);
    try {
      await workerRequest<VideoJob>("batches.update_job", {
        batch_id: current.batch.id,
        job_id: job.id,
        ...changes,
      });
      await refreshBatch(current.batch.id);
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function removeJob(job: VideoJob) {
    if (!current) return;
    setError(null);
    try {
      await workerRequest<BatchView>("batches.remove_job", { batch_id: current.batch.id, job_id: job.id });
      await refreshBatch(current.batch.id);
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function assignBackground(job: VideoJob, assetId: string) {
    if (!current || !assetId) return;
    setError(null);
    try {
      await workerRequest<VideoJob>("batches.override_background", {
        batch_id: current.batch.id,
        job_id: job.id,
        asset_id: assetId,
      });
      await refreshBatch(current.batch.id);
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function assignBulkBackground() {
    if (!current || !bulkAssetId || !selectedJobRows.length) return;
    setBusy(true);
    setError(null);
    let changed = 0;
    try {
      for (const job of selectedJobRows) {
        if (!job.channel_id) continue;
        const belongsToPool = (backgroundPools[job.channel_id] ?? []).some((asset) => asset.id === bulkAssetId && asset.available);
        if (!belongsToPool) continue;
        await workerRequest<VideoJob>("batches.override_background", {
          batch_id: current.batch.id,
          job_id: job.id,
          asset_id: bulkAssetId,
        });
        changed += 1;
      }
      await refreshBatch(current.batch.id);
      setNotice(`Applied the override to ${changed} selected ${changed === 1 ? "job" : "jobs"}.`);
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function applyBulkOutputSettings() {
    if (!current || !selectedJobs.length) return;
    const changed = selectedJobs.length;
    setBusy(true); setError(null);
    try {
      await workerRequest<BatchView>("batches.configure_output_bulk", {
        batch_id: current.batch.id,
        job_ids: selectedJobs,
        ...bulkOutput,
      });
      await refreshBatch(current.batch.id);
      setNotice(`Đã áp dụng profile đầu ra cho ${changed} job.`);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function setBatchThumbnailMode(mode: ThumbnailMode | null) {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<BatchView>("batches.set_thumbnail_mode", { batch_id: current.batch.id, mode });
      await refreshBatch(current.batch.id);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function saveBatchThumbnailPool() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<BatchView>("batches.set_thumbnail_pool", { batch_id: current.batch.id, preset_ids: batchThumbnailPresetIds });
      await refreshBatch(current.batch.id);
      setNotice(batchThumbnailPresetIds.length ? "Batch thumbnail rotation pool saved." : "Thumbnail styles will inherit from each Channel pool.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  function showThumbnailSettings(job: VideoJob) {
    setThumbnailJobId(job.id);
    setThumbnailText(job.thumbnail_text || job.thumbnail_ocr_text || "");
    setError(null);
  }

  async function setJobThumbnailMode(job: VideoJob, mode: ThumbnailMode | null) {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<VideoJob>("jobs.set_thumbnail_mode", { job_id: job.id, mode });
      await refreshBatch(current.batch.id);
      setNotice("Thumbnail mode updated for this job.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function setJobThumbnailPreset(job: VideoJob, presetId: string) {
    if (!current || !presetId) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<VideoJob>("jobs.set_thumbnail_preset", { job_id: job.id, preset_id: presetId });
      await refreshBatch(current.batch.id);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function fetchJobThumbnail(job: VideoJob) {
    setThumbnailText(job.thumbnail_text || job.thumbnail_ocr_text || "");
    await queueJobs([job.id], "thumbnail");
  }

  async function exportJobThumbnail(job: VideoJob) {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      await workerRequest<VideoJob>("jobs.set_thumbnail_text", { job_id: job.id, text: thumbnailText });
      const task = queueTasks.find((item) => item.job_id === job.id && item.pipeline === "thumbnail");
      if (task?.state === "waiting_for_thumbnail_review") {
        await workerRequest<QueueTask>("queue.retry", { task_id: task.id });
        await refreshBatch(current.batch.id);
      } else {
        setBusy(false);
        await queueJobs([job.id], "thumbnail");
        return;
      }
      setNotice("Thumbnail text confirmed. PNG export has resumed in the queue.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function confirmBatch() {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      const confirmed = await workerRequest<BatchView>("batches.confirm", { batch_id: current.batch.id });
      await refreshBatch(confirmed.batch.id);
      setNotice("Batch confirmed. Background assignments are now snapshotted and will stay the same when reopened.");
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  function showSubtitleSettings(job: VideoJob) {
    setSubtitleJobId(job.id);
    setSubtitleOverrideText(job.subtitle_language_override.join(", "));
    setError(null);
  }

  async function saveSubtitleOverride() {
    if (!subtitleJobId || !current) return;
    setBusy(true);
    setError(null);
    try {
      const languages = subtitleOverrideText.split(/[\s,;]+/).filter(Boolean);
      await workerRequest("jobs.set_subtitle_language_override", { job_id: subtitleJobId, languages });
      await refreshBatch(current.batch.id);
      setNotice("Subtitle language preferences updated for this video job.");
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function attachSubtitleFile() {
    if (!subtitleJobId) return;
    try {
      const picked = await open({
        multiple: false,
        title: "Choose SRT or VTT captions",
        filters: [{ name: "Subtitle files", extensions: ["srt", "vtt"] }],
      });
      if (typeof picked !== "string") return;
      await workerRequest("jobs.attach_subtitle_file", { job_id: subtitleJobId, path: picked });
      if (current) await refreshBatch(current.batch.id);
      setNotice("The supplied subtitle is selected because no preferred-language YouTube track matches.");
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function skipCaptions() {
    if (!subtitleJobId || !current) return;
    try {
      await workerRequest("jobs.skip_captions", { job_id: subtitleJobId });
      await refreshBatch(current.batch.id);
      setNotice("Captions will be skipped for this video job.");
    } catch (caught) {
      setError(String(caught));
    }
  }

  async function setSubtitlePreset(job: VideoJob, presetId: string) {
    setBusy(true); setError(null);
    try {
      await workerRequest<VideoJob>("jobs.set_subtitle_preset", { job_id: job.id, preset_id: presetId || null });
      if (current) await refreshBatch(current.batch.id);
      setNotice("Kiểu phụ đề của job đã được cập nhật.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function openRenderSettings(job: VideoJob) {
    setBusy(true); setError(null);
    try {
      const plan = await workerRequest<RenderPlan>("jobs.inspect_render", { job_id: job.id });
      setRenderPlan(plan);
      setRenderJobId(job.id);
      setRenderSettings({ ...job.output_profile, frame_preference: job.output_profile.frame_preference ?? (plan.requires_frame_decision ? null : "profile") });
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function saveRenderSettings() {
    if (!renderJobId) return;
    setBusy(true); setError(null);
    try {
      const plan = await workerRequest<RenderPlan>("jobs.configure_output", { job_id: renderJobId, ...renderSettings });
      setRenderPlan(plan);
      if (current) await refreshBatch(current.batch.id);
      setNotice("Cấu hình đầu ra đã được lưu cho lần render này.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function renderVideo() {
    if (!renderJobId || !current) return;
    const batchId = current.batch.id;
    setBusy(true); setRenderingJobId(renderJobId); setError(null); setNotice(null);
    const progressPoll = window.setInterval(() => {
      void workerRequest<BatchView>("batches.get", { batch_id: batchId })
        .then((latest) => {
          setCurrent(latest);
          const renderingJob = latest.jobs.find((job) => job.id === renderJobId);
          if (renderingJob) setRenderPlan((plan) => plan ? { ...plan, job: renderingJob } : plan);
        })
        .catch(() => undefined);
    }, 900);
    try {
      const configured = await workerRequest<RenderPlan>("jobs.configure_output", { job_id: renderJobId, ...renderSettings });
      setRenderPlan(configured);
      if (configured.requires_frame_decision) {
        setError("Hãy chọn khung hình đầu ra trước khi render.");
        return;
      }
      const rendered = await workerRequest<VideoJob>("jobs.render_video", { batch_id: current.batch.id, job_id: renderJobId });
      await refreshBatch(current.batch.id);
      if (rendered.render_status === "error") setError(rendered.render_error || "Render bị lỗi.");
      else {
        setNotice(`Đã render xong · ${rendered.encoder_used || "H.264"}`);
        setRenderJobId(null); setRenderPlan(null);
      }
    } catch (caught) { setError(String(caught)); }
    finally { window.clearInterval(progressPoll); setBusy(false); setRenderingJobId(null); }
  }

  async function downloadSources(job: VideoJob, includeVideoSource: boolean) {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      let directory = outputDirectory;
      if (!directory) {
        const selectedDirectory = await open({ directory: true, multiple: false, title: "Choose the source media folder" });
        if (typeof selectedDirectory !== "string") return;
        directory = selectedDirectory;
        setOutputDirectory(directory);
      }
      const downloaded = await workerRequest<VideoJob>("jobs.download_sources", {
        batch_id: current.batch.id,
        job_id: job.id,
        output_dir: directory,
        include_video_source: includeVideoSource,
      });
      await refreshBatch(current.batch.id);
      if (downloaded.download_status === "error") setError(downloaded.download_error || "Source download failed.");
      else if (downloaded.download_status === "needs_subtitle_decision") setNotice("Audio and source thumbnail are saved. Choose a subtitle file or skip captions to finish this job’s source step.");
      else setNotice("Source media, thumbnail, and the selected subtitle artifact have been saved locally.");
    } catch (caught) {
      setError(String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function queueJobs(jobIds: string[], pipeline: QueueTask["pipeline"] = "video") {
    if (!current || !jobIds.length) return;
    setBusy(true);
    setError(null);
    try {
      let directory = outputDirectory;
      if (!directory) {
        const selectedDirectory = await open({ directory: true, multiple: false, title: "Choose the output folder for this queue" });
        if (typeof selectedDirectory !== "string") return;
        directory = selectedDirectory;
        setOutputDirectory(directory);
      }
      let result: QueueStatus | null = null;
      for (let index = 0; index < jobIds.length; index += 500) {
        result = await workerRequest<QueueStatus>("queue.start", {
          batch_id: current.batch.id,
          job_ids: jobIds.slice(index, index + 500),
          output_root: directory,
          pipeline,
        });
      }
      if (!result) return;
      setQueueTasks(result.tasks);
      const activeStates = pipeline === "thumbnail" ? ["queued", "downloading", "rendering", "waiting_for_thumbnail_review"] : ["queued", "starting", "downloading", "rendering", "cancel_requested", "waiting_for_captions"];
      const added = result.tasks.filter((task) => task.pipeline === pipeline && jobIds.includes(task.job_id) && activeStates.includes(task.state)).length;
      const label = pipeline === "download_only" ? "download package" : pipeline === "thumbnail" ? "thumbnail" : "video render";
      setNotice(added ? `Added ${added} ${label}${added === 1 ? "" : "s"} to the local queue.` : `Selected ${label} work is already complete or queued.`);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function cancelQueueTask(task: QueueTask) {
    setBusy(true);
    setError(null);
    try {
      await workerRequest<QueueTask>("queue.cancel", { task_id: task.id });
      if (current) await refreshBatch(current.batch.id);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function retryQueueTask(task: QueueTask) {
    setBusy(true);
    setError(null);
    try {
      await workerRequest<QueueTask>("queue.retry", { task_id: task.id });
      if (current) await refreshBatch(current.batch.id);
      setNotice("Job requeued. Valid source files and the confirmed assignment will be reused.");
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  async function setQueueConcurrencyLimit(value: number) {
    setBusy(true);
    setError(null);
    try {
      const result = await workerRequest<{ max_concurrency: number }>("queue.configure", { max_concurrency: value });
      setQueueConcurrency(result.max_concurrency);
      setNotice(`Queue concurrency set to ${result.max_concurrency} job${result.max_concurrency === 1 ? "" : "s"}.`);
    } catch (caught) { setError(String(caught)); }
    finally { setBusy(false); }
  }

  function toggleSelected(jobId: string) {
    setSelectedJobs((currentIds) => currentIds.includes(jobId)
      ? currentIds.filter((id) => id !== jobId)
      : [...currentIds, jobId]);
  }

  const allSelected = Boolean(current?.jobs.length) && selectedJobs.length === current?.jobs.length;
  const subtitleJob = current?.jobs.find((job) => job.id === subtitleJobId) ?? null;
  const thumbnailJob = current?.jobs.find((job) => job.id === thumbnailJobId) ?? null;
  const queueLogTask = queueTasks.find((task) => task.id === queueLogTaskId) ?? null;
  const batchThumbnailPresets = useMemo(() => {
    const presets = current?.jobs.flatMap((job) => job.available_thumbnail_presets) ?? [];
    return [...new Map(presets.map((preset) => [preset.id, preset])).values()] as ThumbnailPreset[];
  }, [current]);

  return (
    <section className="batch-workspace">
      {error && <div className="batch-alert batch-alert-error"><WarningCircle size={17} /><span>{error}</span><button type="button" onClick={() => setError(null)} aria-label="Dismiss"><X size={14} /></button></div>}
      {notice && <div className="batch-alert batch-alert-note"><CheckCircle size={17} /><span>{notice}</span><button type="button" onClick={() => setNotice(null)} aria-label="Dismiss"><X size={14} /></button></div>}

      {current ? (
        <>
          <div className="batch-heading-row">
            <div>
              <button className="batch-back" type="button" onClick={() => { setCurrent(null); setComposer(false); setNotice(null); }}><ArrowLeft size={14} /> All batches</button>
              <div className="batch-eyebrow">{downloadOnly ? "DOWNLOAD ONLY" : "BATCH REVIEW"} <span className={`batch-state ${current.batch.state}`}>{current.batch.state === "draft" ? "Draft" : "Confirmed"}</span></div>
              <h1>{current.batch.name}</h1>
              <p>{current.jobs.length} jobs · {current.batch.ready_count} ready · {current.batch.unresolved_count} need review{downloadOnly ? " · downloads full videos, captions, and original thumbnails" : ""}</p>
              {batchQueueTasks.length > 0 && <div className="batch-queue-progress"><div><span>{completedQueueTasks}/{batchQueueTasks.length} {downloadOnly ? "downloads" : "pipeline tasks"} finished</span><strong>{Math.round(batchQueueProgress * 100)}%</strong></div><progress max="1" value={batchQueueProgress} /></div>}
            </div>
            <div className="batch-actions">
              {isDraft && !downloadOnly && <button className="batch-button batch-button-secondary" type="button" onClick={() => void rebalance()} disabled={busy}><Repeat size={15} /> Rebalance</button>}
              {isDraft && <button className="batch-button batch-button-secondary" type="button" onClick={() => void lookupMetadata()} disabled={busy}><MagnifyingGlass size={15} /> Fetch video details</button>}
              {isDraft && <button className="batch-button batch-button-primary" type="button" onClick={() => void confirmBatch()} disabled={busy || current.batch.ready_count !== current.jobs.length || !current.jobs.length}>{busy ? <CircleNotch className="batch-spin" size={15} /> : <Check size={15} />} {downloadOnly ? "Confirm download list" : "Confirm assignments"}</button>}
              {!isDraft && downloadOnly && <button className="batch-button batch-button-primary" type="button" onClick={() => void queueJobs(current.jobs.map((job) => job.id), "download_only")} disabled={busy || !current.jobs.length}><FolderOpen size={15} /> Download all packages</button>}
              {!isDraft && !downloadOnly && <><button className="batch-button batch-button-primary" type="button" onClick={() => void queueJobs(current.jobs.map((job) => job.id), "video")} disabled={busy || !current.jobs.length}><VideoCamera size={15} /> Queue all videos</button><button className="batch-button batch-button-secondary" type="button" onClick={() => void queueJobs(current.jobs.map((job) => job.id), "thumbnail")} disabled={busy || !current.jobs.length}><ImageSquare size={15} /> Queue thumbnails</button></>}
              {!isDraft && <label className="queue-concurrency-control">Concurrent jobs<select aria-label="Maximum concurrent queue jobs" value={queueConcurrency} onChange={(event) => void setQueueConcurrencyLimit(Number(event.target.value))} disabled={busy}><option value={1}>1 · safe default</option><option value={2}>2</option><option value={3}>3</option><option value={4}>4</option></select></label>}
            </div>
          </div>

          {isDraft && !downloadOnly && <section className="batch-thumbnail-planning">
            <div className="batch-thumbnail-mode">
              <span className="batch-thumbnail-icon"><ImageSquare size={16} /></span>
              <div><strong>Thumbnail workflow</strong><small>Per Channel defaults can be overridden for this Batch.</small></div>
              <select aria-label="Batch thumbnail mode" value={current.batch.thumbnail_mode_override ?? ""} onChange={(event) => void setBatchThumbnailMode(event.target.value ? event.target.value as ThumbnailMode : null)} disabled={busy}>
                <option value="">Inherit from Channel</option><option value="auto">Auto · OCR + presets</option><option value="manual">Manual</option><option value="skip">Skip</option>
              </select>
            </div>
            <details className="batch-thumbnail-pool">
              <summary>{current.batch.thumbnail_preset_ids.length ? current.batch.thumbnail_preset_ids.length + " Batch styles selected" : "Use each Channel’s style pool"}</summary>
              <div className="batch-thumbnail-preset-options">
                {batchThumbnailPresets.map((preset) => <label key={preset.id}><input type="checkbox" checked={batchThumbnailPresetIds.includes(preset.id)} onChange={() => setBatchThumbnailPresetIds((ids) => ids.includes(preset.id) ? ids.filter((id) => id !== preset.id) : [...ids, preset.id])} /><span>{preset.name}</span></label>)}
                {!batchThumbnailPresets.length && <small>Add styles to a Channel from Thumbnail styles before building a rotation pool.</small>}
              </div>
              <button type="button" onClick={() => void saveBatchThumbnailPool()} disabled={busy}>{batchThumbnailPresetIds.length ? "Apply Batch pool" : "Use Channel pools"}</button>
            </details>
          </section>}

          {isDraft && !downloadOnly && selectedJobs.length > 0 && <div className="bulk-toolbar"><span><strong>{selectedJobs.length}</strong> selected</span><div className="bulk-control"><span>Assign shared background</span><select value={bulkAssetId} onChange={(event) => setBulkAssetId(event.target.value)}><option value="">Select a background available to all selected channels</option>{bulkAssetOptions.map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select><button type="button" onClick={() => void assignBulkBackground()} disabled={busy || !bulkAssetId}>Apply</button></div><button type="button" className="bulk-clear" onClick={() => setSelectedJobs([])}>Clear selection</button></div>}
          {isDraft && downloadOnly && selectedJobs.length > 0 && <div className="bulk-toolbar"><span><strong>{selectedJobs.length}</strong> selected</span><div className="bulk-control"><span>Each package includes the full video, preferred captions when available, and original thumbnail.</span></div><button type="button" className="bulk-clear" onClick={() => setSelectedJobs([])}>Clear selection</button></div>}
          {!isDraft && downloadOnly && selectedJobs.length > 0 && <div className="bulk-toolbar"><span><strong>{selectedJobs.length}</strong> job{selectedJobs.length === 1 ? "" : "s"} selected</span><button className="batch-button batch-button-primary" type="button" onClick={() => void queueJobs(selectedJobs, "download_only")} disabled={busy}><FolderOpen size={14} /> Download selected packages</button><button type="button" className="bulk-clear" onClick={() => setSelectedJobs([])}>Clear selection</button></div>}
          {!isDraft && !downloadOnly && selectedJobs.length > 0 && <div className="bulk-toolbar bulk-output-toolbar"><span><strong>{selectedJobs.length}</strong> job{selectedJobs.length === 1 ? "" : "s"} selected</span><div className="bulk-control"><span>Apply output profile</span><select value={bulkOutput.profile} onChange={(event) => setBulkOutput((state) => ({ ...state, profile: event.target.value as OutputProfile["profile"] }))}><option value="720p">720p · 1280×720</option><option value="match_background">Match background</option></select><select aria-label="Frame selection for selected jobs" value={bulkOutput.frame_preference ?? "profile"} onChange={(event) => setBulkOutput((state) => ({ ...state, frame_preference: event.target.value as "profile" | "background" }))}><option value="profile">Keep profile frame</option><option value="background">Use background frame</option></select><select aria-label="Background fit for selected jobs" value={bulkOutput.fit_mode} onChange={(event) => setBulkOutput((state) => ({ ...state, fit_mode: event.target.value as "crop" | "contain" }))}><option value="crop">Crop-to-fill</option><option value="contain">Contain/pad</option></select><button type="button" onClick={() => void applyBulkOutputSettings()} disabled={busy}>Apply to selected</button><button type="button" onClick={() => void queueJobs(selectedJobs, "video")} disabled={busy}>Queue videos</button><button type="button" onClick={() => void queueJobs(selectedJobs, "thumbnail")} disabled={busy}>Queue thumbnails</button></div><button type="button" className="bulk-clear" onClick={() => setSelectedJobs([])}>Clear selection</button></div>}

          <div className="jobs-table-wrap">
            <table className="jobs-table">
              <thead><tr><th className="check-col"><input aria-label="Select all jobs" type="checkbox" checked={allSelected} onChange={(event) => setSelectedJobs(event.target.checked ? current.jobs.map((job) => job.id) : [])} /></th><th className="number-col">#</th><th className="source-col">SOURCE VIDEO</th><th className="channel-col">CHANNEL</th>{!downloadOnly && <th className="background-col">BACKGROUND PLAN</th>}<th className="status-col">REVIEW</th><th className="row-action-col" /></tr></thead>
              <tbody>
                {current.jobs.map((job, index) => {
                  const options = backgroundPools[job.channel_id ?? ""] ?? [];
                  return <tr key={job.id} className={job.readiness !== "ready" ? "job-needs-review" : ""}>
                    <td className="check-col"><input aria-label={`Select row ${job.row_number}`} type="checkbox" checked={selectedJobs.includes(job.id)} onChange={() => toggleSelected(job.id)} /></td>
                    <td className="number-col"><span>{String(index + 1).padStart(2, "0")}</span></td>
                    <td className="source-cell">
                      <div className="source-title">{job.title || (job.readiness === "invalid_url" ? "URL needs correction" : "Video details not loaded")}</div>
                      <div className="source-url"><input aria-label={`YouTube URL row ${job.row_number}`} value={urlEdits[job.id] ?? job.url} onChange={(event) => setUrlEdits((state) => ({ ...state, [job.id]: event.target.value }))} disabled={!isDraft} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void updateJob(job, { url: urlEdits[job.id] ?? job.url }); } }} /><button type="button" onClick={() => void updateJob(job, { url: urlEdits[job.id] ?? job.url })} disabled={!isDraft || (urlEdits[job.id] ?? job.url) === job.url}>Save</button></div>
                      <div className="source-meta">{job.video_id ? <span>ID {job.video_id}</span> : <span>Row {job.row_number}</span>}{job.duration_seconds !== null && <><i /> <span>{formatTime(job.duration_seconds)}</span></>}{job.metadata_error && <span className="metadata-error" title={job.metadata_error}>Lookup failed</span>}</div>
                      <div className="job-source-actions">
                        {job.metadata_status === "ready" && <button type="button" className="job-caption-action" onClick={() => showSubtitleSettings(job)}>{job.selected_subtitle_language ? `Captions · ${job.selected_subtitle_language}` : job.subtitle_decision === "skip" ? "Captions · skipped" : "Choose captions"}</button>}
                        {current.batch.state === "confirmed" && job.download_status === "complete" && <span className="download-complete"><CheckCircle size={12} /> {downloadOnly ? "Package ready" : "Source files saved"}</span>}
                        {current.batch.state === "confirmed" && job.download_status === "needs_subtitle_decision" && <button type="button" className="job-caption-action needs-choice" onClick={() => showSubtitleSettings(job)}>Choose captions or skip</button>}
                        {downloadOnly && current.batch.state === "confirmed" && job.download_status === "complete" && job.source_video_path && <button type="button" className="download-action" onClick={() => void revealItemInDir(job.source_video_path!).catch((caught) => setError(String(caught)))}>Open folder</button>}
                        {downloadOnly && current.batch.state === "confirmed" && job.download_status !== "complete" && !["downloading", "resolving_subtitles", "needs_subtitle_decision"].includes(job.download_status) && !["queued", "starting", "downloading", "cancel_requested", "waiting_for_captions"].includes(job.download_queue_task?.state ?? "") && <button type="button" className="download-action" onClick={() => void queueJobs([job.id], "download_only")} disabled={busy}><FolderOpen size={12} /> {job.download_status === "error" ? "Retry package" : "Download package"}</button>}
                        {!downloadOnly && current.batch.state === "confirmed" && !["complete", "needs_subtitle_decision", "downloading", "resolving_subtitles"].includes(job.download_status) && <><button type="button" className="download-action" onClick={() => void downloadSources(job, false)} disabled={busy}><VideoCamera size={12} /> Audio only</button><button type="button" className="download-action full-source" onClick={() => void downloadSources(job, true)} disabled={busy}>Full source</button></>}
                        {job.download_status === "error" && <span className="download-error" title={job.download_error ?? "Download failed"}>Retry available</span>}
                        {!downloadOnly && current.batch.state === "confirmed" && job.download_status === "complete" && <button type="button" className="render-action" onClick={() => void openRenderSettings(job)} disabled={busy || job.render_status === "rendering"}>{job.render_status === "complete" ? "Render lại" : job.render_status === "error" ? "Thử render lại" : "Cấu hình & render"}</button>}
                        {!downloadOnly && job.render_status === "rendering" && <span className="render-progress-state"><CircleNotch className="batch-spin" size={12} /> {job.render_progress ? `${Math.round(job.render_progress * 100)}%` : "Đang render"}</span>}
                        {!downloadOnly && job.render_status === "complete" && <span className="download-complete" title={`${job.output_video_path ?? ""} · ${job.encoder_used ?? ""}`}><CheckCircle size={12} /> Video sẵn sàng</span>}
                        {!downloadOnly && job.render_status === "error" && <span className="download-error" title={job.render_error ?? "Render failed"}>Render lỗi</span>}
                      </div>
                      {!downloadOnly && <div className="job-thumbnail-tools">
                        <select aria-label={`Thumbnail mode row ${job.row_number}`} value={job.thumbnail_mode_override ?? ""} onChange={(event) => void setJobThumbnailMode(job, event.target.value ? event.target.value as ThumbnailMode : null)} disabled={busy}>
                          <option value="">Default · {job.thumbnail_mode}</option><option value="auto">Auto</option><option value="manual">Manual</option><option value="skip">Skip</option>
                        </select>
                        {job.thumbnail_mode === "auto" && <button type="button" onClick={() => showThumbnailSettings(job)}>{job.thumbnail_ocr_status === "complete" ? "Thumbnail ready" : job.thumbnail_ocr_status === "needs_review" ? "Review OCR" : "Edit thumbnail"}</button>}
                        {job.thumbnail_mode === "manual" && job.source_thumbnail_path && <span title={job.source_thumbnail_path}>Source thumbnail saved</span>}
                      </div>}
                      {downloadOnly && job.download_queue_task && <div className={`job-queue-state ${job.download_queue_task.state}`}>
                        <span>Download package · {job.download_queue_task.state.replace(/_/g, " ")} · {job.download_queue_task.stage.replace(/_/g, " ")}</span>
                        <progress max="1" value={job.download_queue_task.progress} aria-label={`Download progress row ${job.row_number}`} />
                        {job.download_queue_task.error && <small title={job.download_queue_task.error}>{job.download_queue_task.error}</small>}
                        <div>
                          <button type="button" onClick={() => setQueueLogTaskId(job.download_queue_task!.id)}>Logs</button>
                          {["queued", "starting", "downloading", "rendering", "cancel_requested"].includes(job.download_queue_task.state) && queueTasks.some((task) => task.id === job.download_queue_task!.id) && <button type="button" onClick={() => { const task = queueTasks.find((item) => item.id === job.download_queue_task!.id); if (task) void cancelQueueTask(task); }} disabled={busy}>Cancel</button>}
                          {(["failed", "cancelled", "interrupted"].includes(job.download_queue_task.state) || (job.download_queue_task.state === "waiting_for_captions" && job.subtitle_decision !== "needs_decision")) && queueTasks.some((task) => task.id === job.download_queue_task!.id) && <button type="button" onClick={() => { const task = queueTasks.find((item) => item.id === job.download_queue_task!.id); if (task) void retryQueueTask(task); }} disabled={busy}>{job.download_queue_task.state === "waiting_for_captions" ? "Resume" : "Retry"}</button>}
                        </div>
                      </div>}
                      {!downloadOnly && job.queue_task && <div className={`job-queue-state ${job.queue_task.state}`}>
                        <span>Video · {job.queue_task.state.replace(/_/g, " ")} · {job.queue_task.stage.replace(/_/g, " ")}</span>
                        <progress max="1" value={job.queue_task.progress} aria-label={`Queue progress row ${job.row_number}`} />
                        {job.queue_task.error && <small title={job.queue_task.error}>{job.queue_task.error}</small>}
                        <div>
                          <button type="button" onClick={() => setQueueLogTaskId(job.queue_task!.id)}>Logs</button>
                          {["queued", "starting", "downloading", "rendering", "cancel_requested"].includes(job.queue_task.state) && queueTasks.some((task) => task.id === job.queue_task!.id) && <button type="button" onClick={() => { const task = queueTasks.find((item) => item.id === job.queue_task!.id); if (task) void cancelQueueTask(task); }} disabled={busy}>Cancel</button>}
                          {["failed", "cancelled", "interrupted", "waiting_for_captions"].includes(job.queue_task.state) && queueTasks.some((task) => task.id === job.queue_task!.id) && <button type="button" onClick={() => { const task = queueTasks.find((item) => item.id === job.queue_task!.id); if (task) void retryQueueTask(task); }} disabled={busy}>{job.queue_task.state === "waiting_for_captions" ? "Resume" : "Retry"}</button>}
                          {job.queue_task.state === "complete" && job.output_video_path && <button type="button" onClick={() => void revealItemInDir(job.output_video_path!).catch((caught) => setError(String(caught)))}>Open output</button>}
                        </div>
                      </div>}
                      {!downloadOnly && job.thumbnail_queue_task && <div className={`job-queue-state thumbnail ${job.thumbnail_queue_task.state}`}>
                        <span>Thumbnail · {job.thumbnail_queue_task.state.replace(/_/g, " ")} · {job.thumbnail_queue_task.stage.replace(/_/g, " ")}</span>
                        <progress max="1" value={job.thumbnail_queue_task.progress} aria-label={`Thumbnail queue progress row ${job.row_number}`} />
                        {job.thumbnail_queue_task.error && <small title={job.thumbnail_queue_task.error}>{job.thumbnail_queue_task.error}</small>}
                        <div>
                          <button type="button" onClick={() => setQueueLogTaskId(job.thumbnail_queue_task!.id)}>Logs</button>
                          {["queued", "starting", "downloading", "rendering", "cancel_requested"].includes(job.thumbnail_queue_task.state) && queueTasks.some((task) => task.id === job.thumbnail_queue_task!.id) && <button type="button" onClick={() => { const task = queueTasks.find((item) => item.id === job.thumbnail_queue_task!.id); if (task) void cancelQueueTask(task); }} disabled={busy}>Cancel</button>}
                          {["failed", "cancelled", "interrupted", "waiting_for_thumbnail_review"].includes(job.thumbnail_queue_task.state) && queueTasks.some((task) => task.id === job.thumbnail_queue_task!.id) && <button type="button" onClick={() => { const task = queueTasks.find((item) => item.id === job.thumbnail_queue_task!.id); if (task) void retryQueueTask(task); }} disabled={busy}>{job.thumbnail_queue_task.state === "waiting_for_thumbnail_review" ? "Resume export" : "Retry"}</button>}
                          {job.thumbnail_queue_task.state === "complete" && job.thumbnail_output_path && <button type="button" onClick={() => void revealItemInDir(job.thumbnail_output_path!).catch((caught) => setError(String(caught)))}>Open PNG</button>}
                        </div>
                      </div>}
                    </td>
                    <td className="channel-cell"><select value={job.channel_id ?? ""} onChange={(event) => void updateJob(job, { channel_id: event.target.value || null })} disabled={!isDraft}><option value="">Choose channel…</option>{channels.map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}</select></td>
                    {!downloadOnly && <td className="background-cell"><select value={job.background_asset_id ?? ""} onChange={(event) => void assignBackground(job, event.target.value)} disabled={!isDraft || !job.channel_id || !options.length}><option value="">{job.channel_id ? options.length ? "Choose background…" : "No backgrounds in pool" : "Choose channel first"}</option>{options.map((asset) => <option key={asset.id} value={asset.id} disabled={!asset.available}>{asset.name}{!asset.available ? " (missing)" : ""}</option>)}</select></td>}
                    <td className="status-cell"><span className={`readiness-pill ${job.readiness === "ready" ? "ready" : job.readiness === "needs_metadata" ? "pending" : "attention"}`} title={job.flags.join(", ")}><span />{readinessLabel(job)}</span>{job.download_status === "needs_subtitle_decision" && <small className="caption-wait-state">Waiting for captions</small>}</td>
                    <td className="row-action-col">{isDraft && <button type="button" className="job-remove" aria-label={`Remove row ${job.row_number}`} title="Remove job" onClick={() => void removeJob(job)}><Trash size={14} /></button>}</td>
                  </tr>;
                })}
              </tbody>
            </table>
            {!current.jobs.length && <div className="batch-empty-jobs">This batch has no jobs.</div>}
          </div>
          <div className="batch-review-foot"><span><FilmSlate size={14} /> {downloadOnly ? "Each job saves into its own folder under the selected output directory." : "Assignments are stored per job. Rebalancing keeps manual overrides and continues usage counts from confirmed batches."}</span>{isDraft && <button type="button" onClick={() => setComposer(true)}><Plus size={14} /> Import more URLs</button>}</div>
          {composer && <div className="inline-import-panel"><div className="inline-import-top"><div><span className="batch-eyebrow">ADD TO THIS BATCH</span><strong>Import more videos</strong></div><button type="button" aria-label="Close import" onClick={() => setComposer(false)}><X size={15} /></button></div><ImportForm channels={channels} importMode={importMode} setImportMode={setImportMode} workflowMode={current.batch.workflow_mode} setWorkflowMode={setWorkflowMode} channelId={channelId} setChannelId={setChannelId} batchName={current.batch.name} setBatchName={setBatchName} urlText={urlText} setUrlText={setUrlText} fileContent={fileContent} fileName={fileName} onFileChange={readImportFile} onSubmit={importBatch} busy={busy} compact /></div>}
        </>
      ) : composer ? (
        <>
          <div className="batch-heading-row composer-heading"><div><span className="batch-eyebrow">BATCH INTAKE</span><h1>Create a batch</h1><p>Paste URLs by channel or import a Channel + URL file. Choose whether to download for Premiere or render in the app.</p></div><button className="batch-button batch-button-secondary" type="button" onClick={() => setComposer(false)}><ArrowLeft size={15} /> Cancel</button></div>
          <ImportForm channels={channels} importMode={importMode} setImportMode={setImportMode} workflowMode={workflowMode} setWorkflowMode={setWorkflowMode} channelId={channelId} setChannelId={setChannelId} batchName={batchName} setBatchName={setBatchName} urlText={urlText} setUrlText={setUrlText} fileContent={fileContent} fileName={fileName} onFileChange={readImportFile} onSubmit={importBatch} busy={busy} />
        </>
      ) : (
        <>
          <div className="batch-heading-row"><div><span className="batch-eyebrow">BATCH WORKSPACE</span><h1>Video batches</h1><p>Download source packages for Premiere, or prepare and render finished videos.</p></div><button className="batch-button batch-button-primary" type="button" onClick={beginNewBatch}><Plus size={16} weight="bold" /> New batch</button></div>
          {loading ? <div className="batch-loading"><CircleNotch className="batch-spin" size={19} /> Loading local batches…</div> : batches.length ? <div className="batch-list">{batches.map((batch, index) => <button type="button" key={batch.id} className="batch-list-card" onClick={() => void refreshBatch(batch.id)}><span className={`batch-index index-${index % 4}`}>{String(index + 1).padStart(2, "0")}</span><span className="batch-list-copy"><strong>{batch.name}</strong><small>{new Date(batch.created_at).toLocaleString()} · {batch.job_count} jobs · {batch.workflow_mode === "download_only" ? "Download only" : "Render"}</small></span><span className={`batch-list-state ${batch.state}`}>{batch.state === "draft" ? "Draft" : "Confirmed"}</span><span className="batch-readiness-count">{batch.ready_count}/{batch.job_count}<small>READY</small></span><span className="batch-open-chevron">›</span></button>)}</div> : <div className="batch-empty-state"><div><VideoCamera size={24} weight="duotone" /></div><h2>No batches yet</h2><p>Paste a channel’s URLs or import a CSV/TSV with Channel and URL columns.</p><button className="batch-button batch-button-primary" type="button" onClick={beginNewBatch}><Plus size={15} /> Create your first batch</button></div>}
        </>
      )}
      {subtitleJob && current && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSubtitleJobId(null); }}>
          <section className="modal-card subtitle-modal">
            <div className="modal-head"><div><span className="eyebrow">VIDEO JOB CAPTIONS</span><h2>{subtitleJob.title || subtitleJob.video_id || "Subtitle settings"}</h2><p>Channel preference: <strong>{subtitleJob.subtitle_languages.length ? subtitleJob.subtitle_languages.join(" → ") : "none set"}</strong></p></div><button type="button" className="modal-close" aria-label="Close" onClick={() => setSubtitleJobId(null)}><X size={18} /></button></div>
            <label className="field-label" htmlFor="job-language-override">Job language override <span className="subtitle-label-hint">comma-separated priority order; leave blank to inherit the Channel</span></label>
            <div className="subtitle-override-row"><input id="job-language-override" className="text-input" value={subtitleOverrideText} onChange={(event) => setSubtitleOverrideText(event.target.value)} placeholder="e.g. ja, en-US" /><button className="batch-button batch-button-secondary" type="button" onClick={() => void saveSubtitleOverride()} disabled={busy}><Check size={14} /> Apply</button></div>
            <div className="track-inventory">
              <div className="track-inventory-head"><strong>Available YouTube tracks</strong><span>Creator tracks are preferred before auto captions for each language.</span></div>
              {(["creator", "automatic"] as const).map((origin) => {
                const tracks = subtitleJob.subtitle_tracks[origin] ?? [];
                return <div className="track-group" key={origin}><span className="track-origin">{origin === "creator" ? "CREATOR" : "AUTO CAPTIONS"}</span>{tracks.length ? <div className="track-chips">{tracks.map((track) => <span key={track.language} className={subtitleJob.selected_subtitle_language === track.language ? "is-preferred" : ""}>{track.language}{track.formats ? <small>{track.formats}</small> : null}</span>)}</div> : <small className="no-tracks">No tracks found</small>}</div>;
              })}
            </div>
            <label className="field-label job-style-label" htmlFor="job-subtitle-preset">Kiểu hiển thị phụ đề <span className="subtitle-label-hint">Preset có thể ghi đè riêng cho job này.</span></label>
            <select id="job-subtitle-preset" className="text-input" value={subtitleJob.subtitle_preset_id ?? ""} onChange={(event) => void setSubtitlePreset(subtitleJob, event.target.value)} disabled={busy}><option value="">Mặc định của kênh · {subtitleJob.subtitle_preset_name}</option>{subtitleJob.available_subtitle_presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}{preset.channel_id ? " · kênh" : " · dùng chung"}</option>)}</select>
            <div className="job-style-mini-preview"><span style={{ color: subtitleJob.subtitle_style.text_color, backgroundColor: subtitleJob.subtitle_style.background_enabled ? `${subtitleJob.subtitle_style.background_color}${Math.round(subtitleJob.subtitle_style.background_opacity * 255).toString(16).padStart(2, "0")}` : "transparent", fontFamily: subtitleJob.subtitle_style.font_family, fontSize: `${Math.max(10, Math.min(18, subtitleJob.subtitle_style.font_size / 3))}px`, WebkitTextStroke: `0.4px ${subtitleJob.subtitle_style.outline_color}` }}>Your caption appears here</span><small>{subtitleJob.subtitle_preset_name}</small></div>
            {subtitleJob.selected_subtitle_language ? <div className={`subtitle-selected-note ${subtitleJob.selected_subtitle_source === "supplied_file" ? "supplied" : ""}`}><CheckCircle size={16} /><span>Selected: <strong>{subtitleJob.selected_subtitle_language}</strong> · {subtitleJob.selected_subtitle_source === "creator" ? "creator subtitles" : subtitleJob.selected_subtitle_source === "automatic" ? "YouTube auto captions" : subtitleJob.selected_subtitle_source === "supplied_file" ? "supplied subtitle file" : subtitleJob.selected_subtitle_source}</span></div> : subtitleJob.subtitle_decision === "skip" ? <div className="subtitle-selected-note"><CheckCircle size={16} /><span>Captions are set to skip for this job.</span></div> : <div className="subtitle-fallback-actions"><p>No YouTube track matches the preferred languages. Choose an SRT/VTT file or skip captions.</p><div><button className="batch-button batch-button-secondary" type="button" onClick={() => void attachSubtitleFile()}><FolderOpen size={14} /> Choose SRT / VTT</button><button className="batch-button batch-button-secondary" type="button" onClick={() => void skipCaptions()}>Skip captions</button></div></div>}
            {subtitleJob.subtitle_error && <div className="batch-alert batch-alert-error"><WarningCircle size={15} /><span>{subtitleJob.subtitle_error}</span></div>}
            {subtitleJob.supplied_subtitle_path && <div className="supplied-file-path" title={subtitleJob.supplied_subtitle_path}>{subtitleJob.supplied_subtitle_path}</div>}
            <div className="modal-actions"><span className="subtitle-priority-note">A matching YouTube track always takes priority over an attached file.</span><button className="batch-button batch-button-primary" type="button" onClick={() => setSubtitleJobId(null)}>Done</button></div>
          </section>
        </div>
      )}
      {thumbnailJob && current && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) setThumbnailJobId(null); }}>
          <section className="modal-card thumbnail-job-modal">
            <div className="modal-head"><div><span className="eyebrow">VIDEO JOB THUMBNAIL</span><h2>{thumbnailJob.title || thumbnailJob.video_id || "Thumbnail settings"}</h2><p>Mode: <strong>{thumbnailJob.thumbnail_mode}</strong>{thumbnailJob.thumbnail_preset ? " · Style: " + thumbnailJob.thumbnail_preset.name : ""}</p></div><button type="button" className="modal-close" aria-label="Close" onClick={() => setThumbnailJobId(null)} disabled={busy}><X size={18} /></button></div>
            <label className="field-label" htmlFor="job-thumbnail-mode">Processing mode</label>
            <select id="job-thumbnail-mode" className="text-input" value={thumbnailJob.thumbnail_mode_override ?? ""} onChange={(event) => void setJobThumbnailMode(thumbnailJob, event.target.value ? event.target.value as ThumbnailMode : null)} disabled={busy}><option value="">Inherit default · {thumbnailJob.thumbnail_mode}</option><option value="auto">Auto · OCR and export</option><option value="manual">Manual · save source image</option><option value="skip">Skip thumbnail work</option></select>
            {thumbnailJob.thumbnail_mode === "auto" && <>
              <label className="field-label job-thumbnail-preset-label" htmlFor="job-thumbnail-preset">Complete Thumbnail style</label>
              <select id="job-thumbnail-preset" className="text-input" value={thumbnailJob.thumbnail_preset_id ?? ""} onChange={(event) => void setJobThumbnailPreset(thumbnailJob, event.target.value)} disabled={busy || !thumbnailJob.available_thumbnail_presets.length}><option value="">Choose a style</option>{thumbnailJob.available_thumbnail_presets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}</select>
              {thumbnailJob.source_thumbnail_path ? <div className="thumbnail-source-note"><ImageSquare size={15} /><span>Original source image is saved separately from the generated PNG.</span><button type="button" onClick={() => void revealItemInDir(thumbnailJob.source_thumbnail_path!).catch((caught) => setError(String(caught)))}>Show source file</button></div> : <div className="thumbnail-review-note"><WarningCircle size={15} /><span>No source image saved yet. Queue thumbnail work to download and inspect the thumbnail without downloading the YouTube audio.</span></div>}
              {thumbnailJob.thumbnail_queue_task && <div className="render-live-progress"><div><span>Thumbnail queue · {thumbnailJob.thumbnail_queue_task.state.replace(/_/g, " ")}</span><strong>{Math.round(thumbnailJob.thumbnail_queue_task.progress * 100)}%</strong></div><progress max="1" value={thumbnailJob.thumbnail_queue_task.progress} />{thumbnailJob.thumbnail_queue_task.error && <small>{thumbnailJob.thumbnail_queue_task.error}</small>}</div>}
              {thumbnailJob.source_thumbnail_path && <>
                <div className={thumbnailJob.thumbnail_ocr_status === "needs_review" || thumbnailJob.thumbnail_ocr_status === "error" ? "thumbnail-review-note needs-review" : "thumbnail-review-note"}><span>OCR status: <strong>{thumbnailJob.thumbnail_ocr_status.replace(/_/g, " ")}</strong>{thumbnailJob.thumbnail_ocr_confidence !== null ? " · confidence " + Math.round(thumbnailJob.thumbnail_ocr_confidence * 100) + "%" : ""}</span>{thumbnailJob.thumbnail_error && <small>{thumbnailJob.thumbnail_error}</small>}</div>
                <label className="field-label job-thumbnail-text-label" htmlFor="job-thumbnail-text">Recognized text · edit before export</label>
                <textarea id="job-thumbnail-text" className="thumbnail-textarea" value={thumbnailText} onChange={(event) => setThumbnailText(event.target.value)} maxLength={1000} placeholder="OCR text from the source image appears here. Enter it manually if OCR found none." />
                <div className="thumbnail-text-preview" style={{ background: thumbnailJob.thumbnail_preset ? (thumbnailJob.thumbnail_preset.style.background_type === "solid" ? thumbnailJob.thumbnail_preset.style.background_color : "linear-gradient(" + thumbnailJob.thumbnail_preset.style.gradient_angle + "deg, " + thumbnailJob.thumbnail_preset.style.background_color + ", " + thumbnailJob.thumbnail_preset.style.gradient_end_color + ")") : "#34443a" }}><span style={{ color: thumbnailJob.thumbnail_preset?.style.text_color ?? "#fff", fontFamily: (thumbnailJob.thumbnail_preset?.style.font_family ?? "Arial") + ", sans-serif", textAlign: thumbnailJob.thumbnail_preset?.style.alignment ?? "center", WebkitTextStroke: "0.6px " + (thumbnailJob.thumbnail_preset?.style.outline_color ?? "#000"), textShadow: "0 2px 4px #0008" }}>{thumbnailText || "Text preview"}</span></div>
                {thumbnailJob.thumbnail_output_path && <div className="render-output-path" title={thumbnailJob.thumbnail_output_path}>PNG: {thumbnailJob.thumbnail_output_path}</div>}
              </>}
              <div className="thumbnail-job-actions">
                <button className="batch-button batch-button-secondary" type="button" onClick={() => void fetchJobThumbnail(thumbnailJob)} disabled={busy}>{thumbnailJob.thumbnail_queue_task && ["queued", "starting", "downloading", "rendering"].includes(thumbnailJob.thumbnail_queue_task.state) ? "Thumbnail task queued" : thumbnailJob.source_thumbnail_path ? "Queue OCR again" : "Queue source thumbnail + OCR"}</button>
                <button className="batch-button batch-button-primary" type="button" onClick={() => void exportJobThumbnail(thumbnailJob)} disabled={busy || !thumbnailJob.source_thumbnail_path || !thumbnailJob.thumbnail_preset_id || !thumbnailText.trim()}>{busy ? <CircleNotch className="batch-spin" size={14} /> : <ImageSquare size={14} />} Confirm text & queue PNG</button>
              </div>
            </>}
            {thumbnailJob.thumbnail_mode === "manual" && <div className="thumbnail-manual-card"><ImageSquare size={19} /><div><strong>Manual thumbnail handling</strong><span>Queue this pipeline to download only the original thumbnail image, then open it in Canva or another editor.</span>{thumbnailJob.source_thumbnail_path && <small title={thumbnailJob.source_thumbnail_path}>{thumbnailJob.source_thumbnail_path}</small>}</div>{thumbnailJob.source_thumbnail_path ? <button className="batch-button batch-button-secondary" type="button" onClick={() => void revealItemInDir(thumbnailJob.source_thumbnail_path!).catch((caught) => setError(String(caught)))}>Show file</button> : <button className="batch-button batch-button-secondary" type="button" onClick={() => void fetchJobThumbnail(thumbnailJob)} disabled={busy}>Queue image</button>}</div>}
            {thumbnailJob.thumbnail_mode === "skip" && <div className="thumbnail-skip-card"><CheckCircle size={17} /><span>Thumbnail download, OCR, and export are skipped for this job. This does not affect video rendering.</span></div>}
            <div className="modal-actions"><span className="thumbnail-review-footnote">OCR text always comes from the source image, never the YouTube title.</span><button className="batch-button batch-button-primary" type="button" onClick={() => setThumbnailJobId(null)}>Done</button></div>
          </section>
        </div>
      )}
      {renderJobId && renderPlan && current && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) { setRenderJobId(null); setRenderPlan(null); } }}>
          <section className="modal-card render-modal">
            <div className="modal-head"><div><span className="eyebrow">VIDEO EXPORT</span><h2>Cấu hình video đầu ra</h2><p>{renderPlan.background_frame.width}×{renderPlan.background_frame.height} · {renderPlan.background_frame.frame_rate.toFixed(2)} fps từ video nền</p></div><button type="button" className="modal-close" aria-label="Đóng" onClick={() => { setRenderJobId(null); setRenderPlan(null); }} disabled={busy}><X size={18} /></button></div>
            <label className="field-label" htmlFor="render-profile">Export profile</label>
            <select id="render-profile" className="text-input" value={renderSettings.profile} onChange={(event) => setRenderSettings((state) => ({ ...state, profile: event.target.value as OutputProfile["profile"], frame_preference: null }))}>
              <option value="720p">720p · 1280×720 · giữ FPS video nền</option><option value="match_background">Match background · kích thước và FPS gốc</option><option value="custom">Tùy chỉnh</option>
            </select>
            {renderSettings.profile === "custom" && <div className="custom-output-grid"><label>Rộng<input type="number" min="16" step="2" value={renderSettings.custom_width ?? 1280} onChange={(event) => setRenderSettings((state) => ({ ...state, custom_width: Number(event.target.value), frame_preference: null }))} /></label><label>Cao<input type="number" min="16" step="2" value={renderSettings.custom_height ?? 720} onChange={(event) => setRenderSettings((state) => ({ ...state, custom_height: Number(event.target.value), frame_preference: null }))} /></label><label>FPS<input type="number" min="1" max="120" step="0.01" value={renderSettings.custom_frame_rate ?? renderPlan.background_frame.frame_rate} onChange={(event) => setRenderSettings((state) => ({ ...state, custom_frame_rate: Number(event.target.value), frame_preference: null }))} /></label></div>}
            <label className="field-label render-fit-label" htmlFor="render-fit">Cách đưa video nền vào khung</label><select id="render-fit" className="text-input" value={renderSettings.fit_mode} onChange={(event) => setRenderSettings((state) => ({ ...state, fit_mode: event.target.value as "crop" | "contain" }))}><option value="crop">Crop-to-fill · phủ kín khung, có thể cắt mép</option><option value="contain">Contain/pad · giữ trọn hình, thêm viền nếu cần</option></select>
            {renderPlan.has_frame_mismatch && <div className="frame-decision-box"><strong>Tỷ lệ khung khác nhau</strong><span>Nền {renderPlan.background_frame.width}×{renderPlan.background_frame.height}; profile {renderPlan.profile_frame.width}×{renderPlan.profile_frame.height}. Chọn khung video xuất:</span><label><input type="radio" name="frame-preference" checked={renderSettings.frame_preference === "profile"} onChange={() => setRenderSettings((state) => ({ ...state, frame_preference: "profile" }))} /> Giữ khung profile ({renderPlan.profile_frame.width}×{renderPlan.profile_frame.height})</label><label><input type="radio" name="frame-preference" checked={renderSettings.frame_preference === "background"} onChange={() => setRenderSettings((state) => ({ ...state, frame_preference: "background" }))} /> Theo khung video nền ({renderPlan.background_frame.width}×{renderPlan.background_frame.height})</label></div>}
            {renderPlan.job.subtitle_decision === "youtube" || renderPlan.job.subtitle_decision === "use_file" ? <div className="render-caption-note"><CheckCircle size={15} /> Caption sẽ được burn-in và xuất SRT sidecar.</div> : <div className="render-caption-note muted">Job này đã chọn render không caption.</div>}
            {renderPlan.job.render_status === "error" && renderPlan.job.render_error && <div className="batch-alert batch-alert-error"><WarningCircle size={15} /><span>{renderPlan.job.render_error}</span></div>}
            {renderPlan.job.render_status === "rendering" && <div className="render-live-progress"><div><span>Đang render</span><strong>{Math.round((renderPlan.job.render_progress ?? 0) * 100)}%</strong></div><progress max="1" value={renderPlan.job.render_progress ?? 0} /></div>}
            {renderPlan.job.output_video_path && <div className="render-output-path" title={renderPlan.job.output_video_path}>Output hiện tại: {renderPlan.job.output_video_path}</div>}
            <div className="modal-actions"><button type="button" className="batch-button batch-button-secondary" onClick={() => void saveRenderSettings()} disabled={busy}>Lưu cấu hình</button><button type="button" className="batch-button batch-button-primary" onClick={() => void renderVideo()} disabled={busy || (renderPlan.requires_frame_decision && !renderSettings.frame_preference)}>{renderingJobId === renderJobId ? <CircleNotch className="batch-spin" size={15} /> : <FilmSlate size={15} />} {renderingJobId === renderJobId ? "Đang render…" : "Render video"}</button></div>
          </section>
        </div>
      )}
      {queueLogTask && (
        <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setQueueLogTaskId(null); }}>
          <section className="modal-card queue-log-modal">
            <div className="modal-head"><div><span className="eyebrow">{queueLogTask.pipeline.toUpperCase()} QUEUE LOG</span><h2>{queueLogTask.title || queueLogTask.video_id || "Job activity"}</h2><p>{queueLogTask.state.replace(/_/g, " ")} · {queueLogTask.stage.replace(/_/g, " ")}</p></div><button type="button" className="modal-close" aria-label="Close" onClick={() => setQueueLogTaskId(null)}><X size={18} /></button></div>
            <div className="queue-log-list">{queueLogTask.logs?.length ? queueLogTask.logs.map((log, index) => <div className={`queue-log-entry ${log.level}`} key={`${log.created_at}-${index}`}><time>{new Date(log.created_at).toLocaleTimeString()}</time><span>{log.message}</span></div>) : <p>No recorded activity yet.</p>}</div>
            <div className="modal-actions"><button className="batch-button batch-button-primary" type="button" onClick={() => setQueueLogTaskId(null)}>Done</button></div>
          </section>
        </div>
      )}
    </section>
  );
}

type ImportFormProps = {
  channels: Channel[];
  importMode: ImportMode;
  setImportMode: (mode: ImportMode) => void;
  workflowMode: WorkflowMode;
  setWorkflowMode: (mode: WorkflowMode) => void;
  channelId: string;
  setChannelId: (value: string) => void;
  batchName: string;
  setBatchName: (value: string) => void;
  urlText: string;
  setUrlText: (value: string) => void;
  fileContent: string;
  fileName: string;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  busy: boolean;
  compact?: boolean;
};

function ImportForm({ channels, importMode, setImportMode, workflowMode, setWorkflowMode, channelId, setChannelId, batchName, setBatchName, urlText, setUrlText, fileContent, fileName, onFileChange, onSubmit, busy, compact = false }: ImportFormProps) {
  const activeChannels = channels.filter((channel) => channel.active);
  return <form className={`batch-import-card ${compact ? "compact" : ""}`} onSubmit={onSubmit}>
    <div className="import-mode-tabs"><button type="button" className={importMode === "paste" ? "active" : ""} onClick={() => setImportMode("paste")}><VideoCamera size={15} /> Paste under a channel</button><button type="button" className={importMode === "file" ? "active" : ""} onClick={() => setImportMode("file")}><FolderOpen size={15} /> Import CSV / TSV</button></div>
    {!compact && <div className="workflow-mode-picker"><span>What should this batch do?</span><div><button type="button" className={workflowMode === "render" ? "active" : ""} onClick={() => setWorkflowMode("render")}><FilmSlate size={16} /><strong>Prepare & render</strong><small>Background video, captions, and export</small></button><button type="button" className={workflowMode === "download_only" ? "active" : ""} onClick={() => setWorkflowMode("download_only")}><FolderOpen size={16} /><strong>Download only</strong><small>Video + captions + original thumbnail for Premiere</small></button></div></div>}
    {compact && <div className="inline-import-mode"><FolderOpen size={14} /> Adding to a {workflowMode === "download_only" ? "Download only" : "Render"} batch</div>}
    <label className="import-label" htmlFor={compact ? "batch-name-inline" : "batch-name"}>Batch name</label><input id={compact ? "batch-name-inline" : "batch-name"} className="batch-input" value={batchName} onChange={(event) => setBatchName(event.target.value)} placeholder="e.g. Monday upload run" maxLength={100} />
    {importMode === "paste" ? <><label className="import-label" htmlFor={compact ? "batch-channel-inline" : "batch-channel"}>Assign all URLs to</label><select id={compact ? "batch-channel-inline" : "batch-channel"} className="batch-select" value={channelId} onChange={(event) => setChannelId(event.target.value)}><option value="">Choose a channel…</option>{activeChannels.map((channel) => <option value={channel.id} key={channel.id}>{channel.name}{workflowMode === "render" ? ` · ${channel.background_count} backgrounds` : ""}</option>)}</select><label className="import-label" htmlFor={compact ? "batch-urls-inline" : "batch-urls"}>YouTube URLs <span>one URL per line</span></label><textarea id={compact ? "batch-urls-inline" : "batch-urls"} className="batch-textarea" value={urlText} onChange={(event) => setUrlText(event.target.value)} placeholder={"https://www.youtube.com/watch?v=…\nhttps://youtu.be/…\nPaste as many URLs as you need"} rows={compact ? 4 : 8} spellCheck={false} /></> : <><div className="csv-requirements"><strong>Required columns</strong><span>Channel</span><span>URL</span><small>Channel names must match a profile. Unknown names and invalid URLs stay in review for correction.</small></div><label className="csv-file-input"><input type="file" accept=".csv,.tsv,text/csv,text/tab-separated-values" onChange={(event) => void onFileChange(event)} /><span className="csv-file-icon"><FolderOpen size={19} /></span><strong>{fileName || "Choose a CSV or TSV file"}</strong><small>{fileContent ? `${fileContent.split(/\r?\n/).filter(Boolean).length - 1} data rows ready to import` : "Files are read locally and not uploaded"}</small></label></>}
    {!compact && (workflowMode === "download_only" ? <div className="import-assignment-note"><CheckCircle size={15} /> No backgrounds are needed. The app creates one folder per video with the full video, available preferred captions, and original thumbnail.</div> : <div className="import-assignment-note"><CheckCircle size={15} /> Backgrounds will be balanced from each channel’s pool. You can review and override each assignment before confirming.</div>)}
    <div className="import-form-actions"><span>{importMode === "paste" ? "No YouTube video will be downloaded during import." : "CSV parsing runs on this device."}</span><button className="batch-button batch-button-primary" type="submit" disabled={busy || (importMode === "paste" ? !urlText.trim() || !channelId : !fileContent.trim())}>{busy ? <CircleNotch className="batch-spin" size={15} /> : <Plus size={15} />} Import jobs</button></div>
  </form>;
}
