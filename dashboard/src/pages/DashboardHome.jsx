import Panel from "../components/Panel";
import MetricCard from "../components/MetricCard";
import SkillBar from "../components/SkillBar";

function clampPercent(value) {
  return Math.max(0, Math.min(100, Math.round((value || 0) * 100)));
}

function ProgressCard({ title, eyebrow, value, detail, percent, tone = "cyan" }) {
  const fillClass = tone === "blue" ? "bg-blue shadow-[0_0_18px_rgba(87,164,255,0.55)]" : "bg-cyan shadow-[0_0_18px_rgba(60,246,208,0.55)]";

  return (
    <Panel title={title} eyebrow={eyebrow}>
      <div className="space-y-4">
        <div className="flex items-end justify-between gap-4">
          <div>
            <p className="text-4xl font-semibold text-white">{value}</p>
            <p className="mt-2 text-sm text-slate-400">{detail}</p>
          </div>
          <p className="mono text-sm uppercase tracking-[0.25em] text-slate-500">{percent}%</p>
        </div>
        <div className="h-4 overflow-hidden rounded-full border border-white/10 bg-white/5">
          <div className={`h-full rounded-full transition-all duration-700 ${fillClass}`} style={{ width: `${percent}%` }} />
        </div>
      </div>
    </Panel>
  );
}

export default function DashboardHome({
  metrics,
  skills,
  systemStatus,
  policy,
  loopState,
  patches,
  onPolicyToggle,
  adminToken,
  setAdminToken,
}) {
  const learningPercent = clampPercent(metrics.learning_progress);
  const researchPercent = clampPercent(metrics.research_progress);
  const skillEntries = Object.entries(skills || {});
  const agentEntries = Object.entries(metrics.agent_activity?.agents || {});
  const completedResearch = metrics.research_tasks_completed || 0;
  const totalResearch = metrics.research_tasks_total || 0;
  const latestPatch = patches?.[0];

  return (
    <div className="grid gap-6">
      <div className="grid gap-6 xl:grid-cols-[1.35fr,1fr]">
        <Panel title="System Status" eyebrow="Control Plane">
          <div className="grid gap-4 md:grid-cols-2">
            <MetricCard label="Loop State" value={metrics.loop_state} tone="blue" detail={`Version ${systemStatus.version}`} />
            <MetricCard label="AI Confidence" value={`${Math.round((metrics.ai_confidence || 0) * 100)}%`} tone="cyan" detail="Latest scored confidence" />
            <MetricCard label="Loop Iterations" value={metrics.loop_iterations || 0} tone="blue" detail={`Tasks completed ${metrics.tasks_completed || 0} / failed ${metrics.tasks_failed || 0}`} />
            <MetricCard label="Errors 24h" value={metrics.errors_24h} tone={metrics.errors_24h ? "danger" : "blue"} detail={`Debug worker: ${systemStatus.debug_worker_status}`} />
            <MetricCard label="Runtime Status" value={metrics.runtime_running ? "running" : metrics.runtime_paused ? "paused" : "idle"} tone="cyan" detail={`Iteration ${metrics.runtime_iteration || 0}`} />
            <MetricCard label="Active Goal" value={metrics.active_goal || "none"} tone="blue" detail={metrics.last_action || "No runtime action yet"} />
          </div>
        </Panel>

        <Panel title="Auto-Apply Policy Controls" eyebrow="Security">
          <div className="space-y-4">
            <label className="block">
              <span className="mono mb-2 block text-xs uppercase tracking-[0.3em] text-slate-400">Admin Token</span>
              <input
                className="w-full rounded-2xl border border-white/10 bg-black/30 px-4 py-3 text-white outline-none focus:border-cyan/70"
                type="password"
                value={adminToken}
                onChange={(event) => setAdminToken(event.target.value)}
                placeholder="Required for admin actions"
              />
            </label>
            <div className="grid gap-3">
              <button
                className={`rounded-2xl px-4 py-3 text-left ${policy.read_only ? "bg-white/5 text-slate-200" : "bg-cyan/15 text-cyan"}`}
                onClick={() => onPolicyToggle({ read_only: !policy.read_only })}
              >
                Read-Only Mode: {policy.read_only ? "Enabled" : "Disabled"}
              </button>
              <button
                className={`rounded-2xl px-4 py-3 text-left ${policy.admin_mode ? "bg-blue/20 text-blue" : "bg-white/5 text-slate-200"}`}
                onClick={() => onPolicyToggle({ admin_mode: !policy.admin_mode })}
              >
                Admin Mode: {policy.admin_mode ? "Enabled" : "Disabled"}
              </button>
              <button
                className={`rounded-2xl px-4 py-3 text-left ${policy.auto_apply ? "bg-warn/20 text-warn" : "bg-white/5 text-slate-200"}`}
                onClick={() => onPolicyToggle({ auto_apply: !policy.auto_apply })}
              >
                Auto-Apply Policy: {policy.auto_apply ? "Enabled" : "Disabled"}
              </button>
            </div>
            <p className="text-sm text-slate-400">
              Patch approval stays blocked until read-only is disabled and admin mode is enabled with a valid token.
            </p>
          </div>
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <ProgressCard
          title="Learning Progress"
          eyebrow="Learning"
          value={`${learningPercent}%`}
          detail={`${skillEntries.length} tracked skills in the current skill store`}
          percent={learningPercent}
        />

        <ProgressCard
          title="Research Progress"
          eyebrow="Research"
          value={`${completedResearch} / ${totalResearch}`}
          detail="Completed research tasks versus current queue"
          percent={researchPercent}
          tone="blue"
        />
      </div>

      <Panel title="Skill Mastery" eyebrow="Learning">
        <div className="grid gap-4 md:grid-cols-2">
          {skillEntries.length ? (
            skillEntries.map(([name, mastery]) => (
              <SkillBar key={name} skill={name} mastery={mastery} />
            ))
          ) : (
            <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-5 text-sm text-slate-400">
              No skill mastery has been recorded yet. The dashboard will populate this section as the learning system updates the shared skill store.
            </div>
          )}
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel title="Agent Activity" eyebrow="Coordination">
          <div className="grid gap-4 md:grid-cols-2">
            {agentEntries.length ? (
              agentEntries.map(([name, state]) => (
                <div key={name} className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                  <p className="mono text-xs uppercase tracking-[0.3em] text-slate-400">{name}</p>
                  <p className="mt-3 text-xl text-white">{state.status}</p>
                  <p className="mt-2 text-sm text-slate-400">Work Units: {state.work_units}</p>
                </div>
              ))
            ) : (
              <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] p-5 text-sm text-slate-400">
                No coordinated agent activity has been recorded yet.
              </div>
            )}
          </div>
        </Panel>

        <Panel title="Autonomy Loop State" eyebrow="Execution">
          <div className="space-y-4">
            <div className="grid gap-4 md:grid-cols-2">
              <MetricCard label="Current Stage" value={loopState.current_stage || metrics.current_stage || "idle"} tone="cyan" detail={`Loop state ${loopState.loop_state || metrics.loop_state}`} />
              <MetricCard label="Patch Lifecycle" value={metrics.patch_lifecycle?.total_events || 0} tone="blue" detail={latestPatch ? `${latestPatch.patch_type} / ${latestPatch.validation_status}` : "No patch events yet"} />
            </div>
            <div className="flex flex-wrap gap-2">
              {(loopState.pipeline || metrics.loop_pipeline || []).map((stage) => (
                <span
                  key={stage}
                  className={`rounded-full px-3 py-2 text-xs ${
                    (loopState.current_stage || metrics.current_stage) === stage
                      ? "bg-cyan/15 text-cyan"
                      : "bg-white/5 text-slate-300"
                  }`}
                >
                  {stage}
                </span>
              ))}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}
