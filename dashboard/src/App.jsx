import { useEffect, useState } from "react";
import DashboardHome from "./pages/DashboardHome";
import PatchLifecycle from "./pages/PatchLifecycle";
import LiveDebug from "./pages/LiveDebug";
import SystemMetrics from "./pages/SystemMetrics";
import {
  approvePatch,
  fetchDebugStream,
  fetchLoopState,
  fetchMetrics,
  fetchPatches,
  fetchPolicy,
  fetchSkills,
  fetchSystemStatus,
  rollbackPatch,
  updatePolicy,
} from "./api";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "patches", label: "Patch Lifecycle" },
  { id: "debug", label: "Live Debug" },
  { id: "metrics", label: "System Metrics" },
];

function timeLabel() {
  return new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function App() {
  const [activeTab, setActiveTab] = useState("overview");
  const [metrics, setMetrics] = useState({
    cpu: 0,
    memory: 0,
    ai_confidence: 0,
    requests_per_min: 0,
    errors_24h: 0,
    patch_success_rate: 0,
    loop_state: "idle",
  });
  const [systemStatus, setSystemStatus] = useState({
    version: "0.1.0",
    debug_worker_status: "idle",
    last_patch_time: null,
  });
  const [skills, setSkills] = useState({});
  const [policy, setPolicy] = useState({
    read_only: true,
    admin_mode: false,
    auto_apply: false,
  });
  const [patches, setPatches] = useState([]);
  const [loopState, setLoopState] = useState({});
  const [debugStream, setDebugStream] = useState([]);
  const [history, setHistory] = useState([]);
  const [adminToken, setAdminToken] = useState("");
  const [error, setError] = useState("");

  async function load() {
    try {
      const [nextMetrics, nextSkills, nextPatches, nextSystemStatus, nextLoopState, nextDebugStream, nextPolicy] =
        await Promise.all([
          fetchMetrics(),
          fetchSkills(),
          fetchPatches(),
          fetchSystemStatus(),
          fetchLoopState(),
          fetchDebugStream(),
          fetchPolicy(),
        ]);

      setMetrics(nextMetrics);
      setSkills(nextSkills.skills || {});
      setPatches(nextPatches);
      setSystemStatus(nextSystemStatus);
      setLoopState(nextLoopState);
      setDebugStream(nextDebugStream);
      setPolicy(nextPolicy);
      setHistory((current) =>
        [...current, { time: timeLabel(), ...nextMetrics }].slice(-20),
      );
      setError("");
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  useEffect(() => {
    load();
    const handle = window.setInterval(load, 3000);
    return () => window.clearInterval(handle);
  }, []);

  async function handlePolicyToggle(partial) {
    try {
      const updated = await updatePolicy({ ...policy, ...partial }, adminToken);
      setPolicy(updated);
      setError("");
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  async function handleApprove(patchId) {
    try {
      await approvePatch(patchId, adminToken);
      await load();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  async function handleRollback(patchId) {
    try {
      await rollbackPatch(patchId, adminToken);
      await load();
    } catch (nextError) {
      setError(nextError.message);
    }
  }

  return (
    <div className="grid-overlay min-h-screen px-4 py-6 text-white md:px-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-8 flex flex-col gap-6 rounded-[2rem] border border-white/10 bg-black/25 p-6 shadow-glow backdrop-blur">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="mono text-xs uppercase tracking-[0.45em] text-cyan/80">AI Operations</p>
              <h1 className="mt-3 text-4xl font-bold">AIWorker Monitoring Dashboard</h1>
              <p className="mt-3 max-w-3xl text-slate-400">
                Unified visibility into telemetry, patch lifecycle, debugging pipeline, confidence scoring, and policy controls.
              </p>
            </div>
            <div className="rounded-3xl border border-white/10 bg-white/5 px-5 py-4">
              <p className="mono text-xs uppercase tracking-[0.3em] text-slate-400">Last Patch Time</p>
              <p className="mt-2 text-lg text-white">{systemStatus.last_patch_time || "No patch applied yet"}</p>
            </div>
          </div>

          <nav className="flex flex-wrap gap-3">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={`rounded-full px-4 py-2 text-sm transition ${
                  activeTab === tab.id
                    ? "bg-cyan/15 text-cyan"
                    : "bg-white/5 text-slate-300 hover:bg-white/10"
                }`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </header>

        {error ? (
          <div className="mb-6 rounded-2xl border border-danger/40 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {activeTab === "overview" ? (
          <DashboardHome
            metrics={metrics}
            skills={skills}
            systemStatus={systemStatus}
            policy={policy}
            loopState={loopState}
            patches={patches}
            onPolicyToggle={handlePolicyToggle}
            adminToken={adminToken}
            setAdminToken={setAdminToken}
          />
        ) : null}

        {activeTab === "patches" ? (
          <PatchLifecycle patches={patches} policy={policy} onApprove={handleApprove} onRollback={handleRollback} />
        ) : null}

        {activeTab === "debug" ? <LiveDebug loopState={loopState} debugStream={debugStream} /> : null}

        {activeTab === "metrics" ? <SystemMetrics history={history} /> : null}
      </div>
    </div>
  );
}
