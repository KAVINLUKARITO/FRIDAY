import Panel from "../components/Panel";

const PIPELINE = ["SCAN", "ANALYZE", "PROPOSE", "VALIDATE", "APPLY"];

export default function LiveDebug({ loopState, debugStream }) {
  const activeStage = loopState?.last_debug_event?.stage;

  return (
    <div className="grid gap-6 xl:grid-cols-[0.8fr,1.2fr]">
      <Panel title="Pipeline" eyebrow="Live Debug">
        <div className="grid gap-3">
          {PIPELINE.map((stage) => {
            const isActive = stage === activeStage;
            return (
              <div
                key={stage}
                className={`rounded-2xl border px-4 py-3 mono text-sm ${
                  isActive
                    ? "border-cyan/60 bg-cyan/10 text-cyan"
                    : "border-white/10 bg-white/5 text-slate-300"
                }`}
              >
                {stage}
              </div>
            );
          })}
        </div>
      </Panel>

      <Panel title="Live Debug Console" eyebrow="Autonomy Stream">
        <div className="space-y-3">
          {debugStream.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-white/10 p-5 text-slate-400">
              No debug events emitted yet.
            </div>
          ) : (
            debugStream
              .slice()
              .reverse()
              .map((event, index) => (
                <div key={`${event.timestamp}-${index}`} className="rounded-2xl border border-white/10 bg-black/25 p-4">
                  <div className="flex items-center justify-between">
                    <p className="mono text-xs uppercase tracking-[0.3em] text-blue">{event.stage}</p>
                    <span className="text-sm text-slate-500">{event.timestamp}</span>
                  </div>
                  <p className="mt-3 text-sm text-slate-200">Root cause: {event.root_cause || "n/a"}</p>
                  <p className="mt-2 text-sm text-slate-300">Fix proposal: {event.fix_proposal || "n/a"}</p>
                  <p className="mt-2 text-sm text-slate-400">
                    Confidence: {event.confidence == null ? "n/a" : `${Math.round(event.confidence * 100)}%`}
                  </p>
                  <p className="mt-2 text-sm text-slate-400">Validation: {event.validation_result}</p>
                  {event.detail ? <p className="mt-2 text-sm text-slate-500">{event.detail}</p> : null}
                </div>
              ))
          )}
        </div>
      </Panel>
    </div>
  );
}
