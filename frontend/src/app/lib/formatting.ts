export function parseIsoDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatRefreshCountdown(target: Date, nowMs: number): string {
  const remainingMs = Math.max(0, target.getTime() - nowMs);
  const totalSeconds = Math.ceil(remainingMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `Next refresh in ${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function formatRefreshStageLabel(stage: string): string {
  const normalized = stage.trim().toLowerCase();
  if (!normalized) return "Refreshing...";
  if (normalized === "refreshing_pandascore") return "Refreshing PandaScore schedule";
  if (normalized === "refreshing_thunderpick") return "Refreshing Thunderpick odds";
  if (normalized === "placing_bets") return "Placing bets for newly valid matches";
  if (normalized === "finalizing") return "Finalizing refresh";
  if (normalized === "completed") return "Refresh completed";
  if (normalized === "queued") return "Refresh queued";
  return normalized.replace(/_/g, " ");
}
