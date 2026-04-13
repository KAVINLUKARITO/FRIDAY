import Panel from "../components/Panel";

export default function PatchLifecycle({ patches, policy, onApprove, onRollback }) {
  return (
    <Panel title="Patch Lifecycle Timeline" eyebrow="Lifecycle">
      <div className="space-y-4">
        {patches.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 p-5 text-slate-400">
            No lifecycle events recorded yet.
          </div>
        ) : (
          patches.map((patch) => (
            <div key={patch.id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                <div>
                  <p className="mono text-xs uppercase tracking-[0.3em] text-cyan/80">{patch.patch_type}</p>
                  <h3 className="mt-1 text-lg font-semibold text-white">{patch.result || "Lifecycle event"}</h3>
                  <p className="mt-2 text-sm text-slate-400">{patch.timestamp}</p>
                  <p className="mt-2 text-sm text-slate-300">Validation: {patch.validation_status}</p>
                  <p className="mt-2 text-sm text-slate-400">Files: {(patch.file_changed || []).join(", ") || "n/a"}</p>
                </div>
                <div className="flex gap-3">
                  <button
                    className="rounded-2xl bg-cyan/15 px-4 py-2 text-cyan disabled:cursor-not-allowed disabled:bg-white/5 disabled:text-slate-500"
                    disabled={policy.read_only || !policy.admin_mode}
                    onClick={() => onApprove(patch.id)}
                  >
                    Approve
                  </button>
                  <button
                    className="rounded-2xl bg-danger/15 px-4 py-2 text-danger disabled:cursor-not-allowed disabled:bg-white/5 disabled:text-slate-500"
                    disabled={!policy.admin_mode}
                    onClick={() => onRollback(patch.id)}
                  >
                    Rollback
                  </button>
                </div>
              </div>
              {patch.diff ? (
                <pre className="mono mt-4 overflow-x-auto rounded-2xl bg-black/30 p-4 text-xs text-slate-300">
                  {patch.diff}
                </pre>
              ) : null}
            </div>
          ))
        )}
      </div>
    </Panel>
  );
}
