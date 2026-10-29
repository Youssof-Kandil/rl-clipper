import type { Job } from "../api";

interface Props {
  label: string;
  job: Pick<Job, "status" | "progress" | "message" | "error"> & Partial<Pick<Job, "result">>;
  onCancel?: () => void;
  /** List the files a finished export wrote. */
  files?: boolean;
}

export default function JobBar({ label, job, onCancel, files }: Props) {
  const running = ["queued", "running"].includes(job.status);
  return (
    <div className={`jobbar ${job.status}`}>
      <div className="jobbar-text">
        <strong>{label}</strong>
        <span className="muted">{job.status === "error" ? job.error : job.message || job.status}</span>
        {onCancel && running && (
          <button className="ghost small" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      <div className="progress">
        <div style={{ width: `${Math.round(job.progress * 100)}%` }} />
      </div>
      {files && job.status === "done" && job.result?.files && (
        <ul className="files">
          {job.result.files.map((f) => (
            <li key={f.path} title={f.path}>
              ✓ {f.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
